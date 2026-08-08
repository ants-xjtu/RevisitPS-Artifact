package(default_visibility = ["//visibility:public"])
load("@my_deps//:requirements.bzl", "requirement")
load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "cpustat",
    srcs = ["cpustat.py"],
    deps = [
        requirement("numpy"),
        requirement("matplotlib"),
        requirement("pandas"),
    ]
)

py_library(
    name = "mpstat",
    srcs = ["mpstat.py"],
    deps = [
        requirement("pandas"),
    ]
)

py_library(
    name = "dstat",
    srcs = ["dstat.py"],
    deps = [
        requirement("pandas"),
    ]
)

py_library(
    name = "sysstat",
    srcs = ["sysstat.py"],
    deps = [
        requirement("pandas"),
    ]
)
