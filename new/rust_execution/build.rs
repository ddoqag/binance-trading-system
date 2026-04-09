use std::env;
use std::path::PathBuf;

fn main() {
    // Tell cargo to rerun if source files change
    println!("cargo:rerun-if-changed=src/");

    // Set optimization flags for release builds
    let profile = env::var("PROFILE").unwrap_or_default();
    if profile == "release" {
        // Ensure we use all CPU features
        println!("cargo:rustc-env=RUSTFLAGS=-C target-cpu=native");
    }
}
