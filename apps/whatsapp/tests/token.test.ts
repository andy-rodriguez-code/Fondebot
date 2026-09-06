import assert from "node:assert/strict";
import { test } from "node:test";

import { bridgeToken, tokenMatches } from "../src/api.js";

// The FastAPI side has always compared this same shared secret with
// hmac.compare_digest; this side used `!==`, which short-circuits on the first
// differing byte. These do not measure time — a wall clock is not a reliable
// assertion — they pin the behaviour a constant-time comparison must keep.

test("accepts the configured token", () => {
  assert.equal(tokenMatches(bridgeToken), true);
});

test("rejects a token that shares a long prefix", () => {
  // The case `!==` leaked: everything but the last byte correct.
  const almost = bridgeToken.slice(0, -1) + (bridgeToken.endsWith("z") ? "y" : "z");
  assert.equal(almost.length, bridgeToken.length);
  assert.equal(tokenMatches(almost), false);
});

test("rejects a shorter and a longer token without throwing", () => {
  // timingSafeEqual throws on mismatched buffer lengths, so the length check
  // has to come first or an attacker crashes the handler instead of failing.
  assert.equal(tokenMatches(bridgeToken.slice(0, -1)), false);
  assert.equal(tokenMatches(bridgeToken + "x"), false);
});

test("rejects a missing or non-string header", () => {
  // node:http gives string[] for a repeated header and undefined for an absent
  // one; neither may be treated as a match.
  assert.equal(tokenMatches(undefined), false);
  assert.equal(tokenMatches([bridgeToken]), false);
  assert.equal(tokenMatches(""), false);
});
