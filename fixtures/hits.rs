//! This crate serves as the entry point.

/// A pivotal step — runs first.
fn f<'a>(x: &'a str) -> &'a str {
    x // it is not just a cache, but a build farm
}
