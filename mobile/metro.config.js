const { getDefaultConfig } = require("expo/metro-config");
const { withNativeWind } = require("nativewind/metro");
const path = require("path");

const config = getDefaultConfig(__dirname);
// Allow importing the shared package from the monorepo.
config.watchFolders = [path.resolve(__dirname, "../packages/shared")];
module.exports = withNativeWind(config, { input: "./global.css" });
