"use strict";

const fs = require("node:fs");
const twitterText = require("twitter-text");

const input = JSON.parse(fs.readFileSync(0, "utf8"));
if (typeof input !== "string") {
  throw new TypeError("Expected one JSON string on stdin");
}

const text = input.normalize("NFC");
const parsed = twitterText.parseTweet(text);
const urls = twitterText.extractUrls(text);

process.stdout.write(
  JSON.stringify({
    text,
    valid: parsed.valid,
    weightedLength: parsed.weightedLength,
    urls,
  }),
);

