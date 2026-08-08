load("@rules_python//python:pip.bzl", "compile_pip_requirements")

# Run `bazel run requirements.update` to update requirements
compile_pip_requirements(
    name = "requirements",
    extra_args = ["--allow-unsafe"],
    requirements_in = "//third_party/py:requirements.in",
    requirements_txt = "//third_party/py:requirements_lock.txt",
)
