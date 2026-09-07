const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const test = require("node:test");

const source = fs.readFileSync(new URL("../Model.js", `file://${__dirname}/`), "utf8")
  .replace(/^\.pragma library\s*/m, "");
const model = {};
vm.createContext(model);
vm.runInContext(source, model);

test("parseConfig normalizes persisted values into ac/battery pairs", () => {
  assert.deepEqual(
    JSON.parse(JSON.stringify(model.parseConfig(
      '{"screensaver":{"ac":600,"battery":120},"lock":{"ac":900,"battery":300}}'
    ))),
    {
      screensaver: { ac: 600, battery: 120 },
      display: { ac: 0, battery: 0 },
      lock: { ac: 900, battery: 300 },
      sleep: { ac: 0, battery: 0 },
      hibernate: { ac: 0, battery: 0 },
      lid: { ac: "system", battery: "system" }
    }
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(model.parseConfig("broken"))),
    {
      screensaver: { ac: 150, battery: 150 },
      display: { ac: 0, battery: 0 },
      lock: { ac: 300, battery: 300 },
      sleep: { ac: 0, battery: 0 },
      hibernate: { ac: 0, battery: 0 },
      lid: { ac: "system", battery: "system" }
    }
  );
});

test("parseConfig fills a missing side of a pair with the same default", () => {
  // A partial object (e.g. hand-edited, or written by an older config)
  // should not leave the missing side undefined.
  const parsed = model.parseConfig('{"lock":{"ac":900}}');
  assert.equal(parsed.lock.ac, 900);
  assert.equal(parsed.lock.battery, 300);
});

test("effectiveSeconds resolves the right side of a pair", () => {
  const pair = { ac: 600, battery: 120 };
  assert.equal(model.effectiveSeconds(pair, false, 0, true), 600);
  assert.equal(model.effectiveSeconds(pair, true, 0, true), 120);
});

test("effectiveSeconds falls back when the pair itself is missing", () => {
  assert.equal(model.effectiveSeconds(undefined, false, 42, true), 42);
});

test("lid actions are normalized and labelled per power state", () => {
  assert.equal(model.normalizedLidAction("display"), "display");
  assert.equal(model.normalizedLidAction("invalid"), "system");
  assert.equal(model.lidActionLabel("nothing"), "Do nothing");
  assert.equal(model.lidActionLabel("system"), "System default");

  const lidPair = model.parseConfig('{"lid":{"ac":"nothing","battery":"hibernate"}}').lid;
  assert.equal(lidPair.ac, "nothing");
  assert.equal(lidPair.battery, "hibernate");
  assert.equal(model.effectiveLidAction(lidPair, false), "nothing");
  assert.equal(model.effectiveLidAction(lidPair, true), "hibernate");
});

test("formatDuration produces compact labels", () => {
  assert.equal(model.formatDuration(0), "Off");
  assert.equal(model.formatDuration(300), "5 min");
  assert.equal(model.formatDuration(3600), "1 hour");
  assert.equal(model.formatDuration(7200), "2 hours");
});

test("requestedSeconds rejects unusable values instead of coercing to Off", () => {
  assert.equal(model.requestedSeconds(-5), -1);
  assert.equal(model.requestedSeconds("nonsense"), -1);
  assert.equal(model.requestedSeconds(Infinity), -1);
  // 0 is only ever Off when the caller asks for it explicitly.
  assert.equal(model.requestedSeconds(0), 0);
  assert.equal(model.requestedSeconds(900), 900);
});

test("requestedSeconds rejects oversized values rather than clamping them", () => {
  // Clamping would turn an absurd setLock into a seven-day timeout, the same
  // silent weakening this guard exists to prevent. Reject, as the CLI does.
  assert.equal(model.requestedSeconds(2000000000), -1);
  assert.equal(model.requestedSeconds(model.maxTimeoutSeconds + 1), -1);
  assert.equal(model.requestedSeconds(model.maxTimeoutSeconds), model.maxTimeoutSeconds);
});

test("normalizedSeconds clamps persisted values below the 32-bit overflow", () => {
  // A config written before the bounds existed has no caller to reject to.
  assert.equal(model.normalizedSeconds(2000000000, 0, true), model.maxTimeoutSeconds);
  assert.ok(model.maxTimeoutSeconds * 1000 < 2147483647);
});

test("parseConfig bounds oversized persisted values on both sides", () => {
  const parsed = model.parseConfig('{"sleep":{"ac":2000000000,"battery":2000000000}}');
  assert.equal(parsed.sleep.ac, model.maxTimeoutSeconds);
  assert.equal(parsed.sleep.battery, model.maxTimeoutSeconds);
  assert.ok(parsed.sleep.ac * 1000 < 2147483647);
});

test("statusSummary includes all stages for already-resolved effective values", () => {
  assert.equal(
    model.statusSummary(300, 120, 600, 1800, 7200),
    "Screen 5 min · Displays 2 min · Lock 10 min · Sleep 30 min · Hibernate +2 hours"
  );
});

test("parseConfig normalizes the hibernate-after-sleep delay per power state", () => {
  assert.equal(model.parseConfig('{"hibernate":{"ac":7200,"battery":3600}}').hibernate.ac, 7200);
  assert.equal(model.parseConfig('{"hibernate":{"ac":7200,"battery":3600}}').hibernate.battery, 3600);
  assert.equal(model.parseConfig('{"hibernate":{"ac":-1,"battery":-1}}').hibernate.ac, 0);
});
