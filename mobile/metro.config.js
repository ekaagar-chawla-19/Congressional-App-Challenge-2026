// expo-sqlite on web loads its SQLite build as a .wasm asset.
// https://docs.expo.dev/versions/v58.0.0/sdk/sqlite/#web-setup
const { getDefaultConfig } = require('expo/metro-config');

const config = getDefaultConfig(__dirname);
config.resolver.assetExts.push('wasm');

module.exports = config;
