#!/usr/bin/env python3
"""
Build LibEVMU.xcframework — the Apple packaging of libElysianVMU (libevmu) for
iFly.  Mirrors the flycast xcframework build: per-platform CMake static-lib
builds, merged into one archive per slice, wrapped as an xcframework with a
proper umbrella header + clang module map so Swift can `import LibEVMU`.

libevmu's public API rides on libgimbal (a GObject-style C type system), so the
static lib is actually 5 archives (libevmu + libGimbal + tiny-regex-c +
tinycthread + lz4) that we merge with `libtool -static`.  No profiling, no tests
(GBL/EVMU test suites default OFF).

Usage:
    python3 build_xcframework.py --platforms ios ios-simulator tvos tvos-simulator
    python3 build_xcframework.py --platforms ios-simulator          # fast single slice
"""
import argparse, glob, os, shutil, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(ROOT, "build_xcframework")
OUT = os.path.join(ROOT, "xcframework", "LibEVMU.xcframework")
DEPLOY = "17.0"

# platform -> (CMAKE_SYSTEM_NAME, CMAKE_OSX_SYSROOT)
PLATFORMS = {
    "ios":            ("iOS",   "iphoneos"),
    "ios-simulator":  ("iOS",   "iphonesimulator"),
    "tvos":           ("tvOS",  "appletvos"),
    "tvos-simulator": ("tvOS",  "appletvsimulator"),
    "watchos":        ("watchOS", "watchos"),
    "watchos-simulator": ("watchOS", "watchsimulator"),
}

# The 5 static archives CMake emits (basename patterns, searched recursively).
ARCHIVES = ["liblibLibElysianVMU.a", "liblibGimbal.a",
            "libTinyRegexC.a", "libtinycthread.a", "liblz4.a"]

# libgimbal/libevmu take their build configuration as CMake compile-line -D
# flags (GBL_CONFIG_*, EVMU_RESULT_*) — the public headers REFERENCE these but
# never define them, so a headers-only clang-module parse fails with "use of
# undeclared identifier GBL_CONFIG_*". We bake the same values the archives were
# compiled with into the umbrella (guarded, so a consumer -D still wins), making
# the header set self-contained. Values mirror the EVMU/GBL CMake defaults.
CONFIG_DEFINES = [
    ("GBL_CONFIG_ASSERT_PARTIAL_ENABLED", "0"),
    ("GBL_CONFIG_ASSERT_ERROR_ENABLED",   "0"),
    ("GBL_CONFIG_ASSERT_UNKNOWN_ENABLED", "0"),
    ("GBL_CONFIG_LOG_PARTIAL_ENABLED",    "1"),
    ("GBL_CONFIG_LOG_ERROR_ENABLED",      "1"),
    ("GBL_CONFIG_LOG_UNKNOWN_ENABLED",    "1"),
    ("GBL_CONFIG_LOG_PARTIAL_LEVEL",      "GBL_LOG_LEVEL_WARNING"),
    ("GBL_CONFIG_LOG_ERROR_LEVEL",        "GBL_LOG_LEVEL_ERROR"),
    ("GBL_CONFIG_LOG_UNKNOWN_LEVEL",      "GBL_LOG_LEVEL_ERROR"),
    ("GBL_CONFIG_ERRNO_CHECKS",           "1"),
    ("GBL_CONFIG_PREFETCH_ENABLED",       "1"),
    ("GBL_TLS_EMULATED",                  "0"),
    ("GBL_BIG_ENDIAN",                    "0"),
    ("EVMU_RESULT_ERROR_ASSERT",          "1"),
    ("EVMU_RESULT_ERROR_LOG",             "1"),
    ("EVMU_RESULT_CONTEXT_TRACK_LAST_ERROR", "1"),
    ("EVMU_RESULT_CALL_STACK_TRACKING",   "1"),
]


def run(cmd, **kw):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def build_slice(platform):
    system, sysroot = PLATFORMS[platform]
    bdir = os.path.join(BUILD, platform)
    run(["cmake", "-S", ROOT, "-B", bdir, "-GXcode",
         f"-DCMAKE_SYSTEM_NAME={system}",
         f"-DCMAKE_OSX_SYSROOT={sysroot}",
         "-DCMAKE_OSX_ARCHITECTURES=arm64",
         f"-DCMAKE_OSX_DEPLOYMENT_TARGET={DEPLOY}",
         "-DEVMU_ENABLE_TESTS=OFF", "-DGBL_ENABLE_TESTS=OFF"])
    run(["cmake", "--build", bdir, "--target", "libLibElysianVMU",
         "--config", "Release", "--", "-quiet"])

    # Collect the 5 archives and merge into one fat static lib for this slice.
    libs = []
    for name in ARCHIVES:
        hits = glob.glob(os.path.join(bdir, "**", name), recursive=True)
        if not hits:
            sys.exit(f"error: {name} not found under {bdir}")
        libs.append(sorted(hits, key=len)[0])
    merged = os.path.join(BUILD, f"libLibEVMU-{platform}.a")
    run(["libtool", "-static", "-o", merged] + libs)
    return merged


def stage_headers():
    """Assemble the shared Headers dir: evmu + gimbal public trees, a generated
    umbrella (LibEVMU.h) and the clang module map."""
    hdir = os.path.join(BUILD, "Headers")
    if os.path.isdir(hdir):
        shutil.rmtree(hdir)
    os.makedirs(hdir)
    shutil.copytree(os.path.join(ROOT, "lib", "api", "evmu"),
                    os.path.join(hdir, "evmu"))
    shutil.copytree(os.path.join(ROOT, "lib", "lib", "libgimbal", "lib", "api", "gimbal"),
                    os.path.join(hdir, "gimbal"))
    shutil.copy(os.path.join(ROOT, "apple", "module.modulemap"),
                os.path.join(hdir, "module.modulemap"))
    shutil.copy(os.path.join(ROOT, "apple", "LibEVMUShim.h"),
                os.path.join(hdir, "LibEVMUShim.h"))

    # Generate the umbrella by including every public evmu header. evmu headers
    # pull gimbal transitively via <gimbal/...>; both trees sit under Headers/ so
    # <evmu/...> and <gimbal/...> resolve. Headers are self-contained (include
    # guards + own deps), so include order is irrelevant.
    evmu_headers = sorted(
        os.path.relpath(p, hdir)
        for p in glob.glob(os.path.join(hdir, "evmu", "**", "*.h"), recursive=True))
    with open(os.path.join(hdir, "LibEVMU.h"), "w") as f:
        f.write("// Umbrella header for the LibEVMU clang module. AUTO-GENERATED.\n")
        f.write("#ifndef LIBEVMU_UMBRELLA_H\n#define LIBEVMU_UMBRELLA_H\n\n")
        f.write("// Build configuration (normally CMake -D flags) baked in so the\n"
                "// header set is self-contained for a clang module.\n")
        for name, val in CONFIG_DEFINES:
            f.write(f"#ifndef {name}\n#define {name} {val}\n#endif\n")
        f.write("\n")
        for h in evmu_headers:
            f.write(f"#include <{h}>\n")
        f.write('\n#include "LibEVMUShim.h"  // Swift-callable IBehavior wrappers\n')
        f.write("\n#endif\n")
    print(f"  umbrella includes {len(evmu_headers)} evmu headers")
    prune_unused_gimbal_headers(hdir)
    return hdir


def prune_unused_gimbal_headers(hdir):
    """Ship only the gimbal headers the umbrella actually pulls. libevmu vendors
    all 107 gimbal public headers (incl. C++ .hpp and test/ headers the C API
    never uses); leaving them in Headers/ makes clang warn "umbrella does not
    include header ..." for each. We compute the real transitive set with
    `clang -M` and delete the rest, yielding a clean, minimal, warning-free
    clang module."""
    sdk = subprocess.check_output(
        ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-path"], text=True).strip()
    out = subprocess.check_output(
        ["clang", "-M", "-x", "c", os.path.join(hdir, "LibEVMU.h"),
         "-I", hdir, "-isysroot", sdk,
         "-target", "arm64-apple-ios17.0-simulator"],
        text=True, stderr=subprocess.DEVNULL)
    gimbal_root = os.path.join(hdir, "gimbal")
    needed = {os.path.realpath(tok) for tok in out.replace("\\", " ").split()
              if tok.endswith(".h") and os.path.realpath(tok).startswith(os.path.realpath(gimbal_root))}
    removed = 0
    for path in glob.glob(os.path.join(gimbal_root, "**", "*.h*"), recursive=True):
        if os.path.realpath(path) not in needed:
            os.remove(path)
            removed += 1
    kept = len(glob.glob(os.path.join(gimbal_root, "**", "*.h"), recursive=True))
    print(f"  gimbal headers: kept {kept}, pruned {removed} unused")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--platforms", nargs="+", default=["ios", "ios-simulator"],
                    choices=list(PLATFORMS))
    args = ap.parse_args()

    merged = {p: build_slice(p) for p in args.platforms}
    headers = stage_headers()

    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    cmd = ["xcodebuild", "-create-xcframework"]
    for p in args.platforms:
        cmd += ["-library", merged[p], "-headers", headers]
    cmd += ["-output", OUT]
    run(cmd)
    print(f"\n✅ {OUT}")


if __name__ == "__main__":
    main()
