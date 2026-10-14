// the phrase "serves as the" is mentioned, not used
fn f<'a>(x: &'a str) -> &'a str {
    let _ = r#"// pivotal "quoted" — I hope this helps"#;
    let _ = '"';
    let _ = b'\'';
    /* outer /* nested */ still a comment, nothing to flag */
    x
}
