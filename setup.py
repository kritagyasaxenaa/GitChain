from __future__ import annotations

import shlex
import subprocess

from pybind11.setup_helpers import Pybind11Extension, build_ext
from setuptools import setup


def pkg_config_flags(*packages: str) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    try:
        compile_flags = shlex.split(
            subprocess.check_output(["pkg-config", "--cflags", *packages], text=True)
        )
        link_flags = shlex.split(
            subprocess.check_output(["pkg-config", "--libs", *packages], text=True)
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "Missing native development dependencies. Install pkg-config, OpenSSL, RocksDB, "
            "libpqxx, Boost, and nlohmann-json before installing GitChain."
        ) from exc

    include_dirs = [flag[2:] for flag in compile_flags if flag.startswith("-I")]
    compile_options = [flag for flag in compile_flags if not flag.startswith("-I")]
    library_dirs = [flag[2:] for flag in link_flags if flag.startswith("-L")]
    libraries = [flag[2:] for flag in link_flags if flag.startswith("-l")]
    link_options = [
        flag for flag in link_flags if not flag.startswith(("-L", "-l"))
    ]
    return include_dirs, compile_options, library_dirs, libraries, link_options


(
    native_include_dirs,
    native_compile_options,
    native_library_dirs,
    native_libraries,
    native_link_options,
) = pkg_config_flags("openssl", "rocksdb", "libpqxx")

setup(
    packages=["gitchain"],
    package_dir={"": "."},
    ext_modules=[
        Pybind11Extension(
            "goc_core",
            sources=[
                "src/bindings.cpp",
                "src/AccessControl.cpp",
                "src/Block.cpp",
                "src/Consensus.cpp",
                "src/CreateBlock.cpp",
                "src/Crypto.cpp",
                "src/PostGres.cpp",
                "src/UserReg.cpp",
            ],
            include_dirs=["include", *native_include_dirs],
            library_dirs=native_library_dirs,
            libraries=native_libraries,
            extra_compile_args=[*native_compile_options, "-Wall", "-Wextra", "-Wpedantic"],
            extra_link_args=native_link_options,
            cxx_std=20,
        )
    ],
    cmdclass={"build_ext": build_ext},
)