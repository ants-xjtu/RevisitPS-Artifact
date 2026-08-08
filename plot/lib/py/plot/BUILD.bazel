package(default_visibility = ["//visibility:public"])
load("@my_deps//:requirements.bzl", "requirement")
load("@rules_python//python:defs.bzl", "py_library")

exports_files(["paper.mplstyle"])

py_library(
    name = "plot",
    srcs = ["plot.py"],
    data = ["paper.mplstyle"],
    deps = [
        "//lib/py/utils:stat",
        requirement("matplotlib"),
    ],
)
