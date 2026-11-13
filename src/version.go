package main

import (
	"runtime"
	"runtime/debug"
)

// Direct builds use these defaults unless linker flags supply release metadata.
var version = "dev"
var buildTime = "unknown"

type versionInfo struct {
	AppVersion string `json:"app_version"`
	Commit     string `json:"commit"`
	BuildTime  string `json:"build_time"`
	GoVersion  string `json:"go_version"`
}

func currentVersion() versionInfo {
	commit := "unknown"
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, setting := range info.Settings {
			if setting.Key == "vcs.revision" && setting.Value != "" {
				commit = setting.Value
				break
			}
		}
	}
	return versionInfo{version, commit, buildTime, runtime.Version()}
}
