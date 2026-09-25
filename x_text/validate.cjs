const fs = require('fs');
const twitter = require('twitter-text');
const text = JSON.parse(fs.readFileSync(0, 'utf8')).normalize('NFC');
const result = twitter.parseTweet(text);
process.stdout.write(JSON.stringify({text, weightedLength: result.weightedLength,
  valid: result.valid, urls: twitter.extractUrls(text)}));
