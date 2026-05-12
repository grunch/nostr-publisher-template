use std::time::Duration;

use anyhow::{Context, Result};
use clap::Parser;
use nostr_sdk::prelude::*;

const DEFAULT_PRIMARY_RELAYS: &[&str] = &[
    "wss://relay.mostro.network",
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.snort.social",
    "wss://relay.nostr.band",
];

const DEFAULT_SECONDARY_RELAYS: &[&str] = &[
    "wss://nostr.wine",
    "wss://nostr.mom",
    "wss://nostr.bitcoiner.social",
    "wss://nostr-pub.wellorder.net",
    "wss://relay.nostr.bg",
    "wss://relay.nostr.com.au",
];

const DEFAULT_EXPANSION_RELAYS: &[&str] = &[
    "wss://atlas.nostr.land",
    "wss://eden.nostr.land",
    "wss://puravida.nostr.land",
    "wss://nostr.inosta.cc",
    "wss://nostr.oxtr.dev",
    "wss://relay.noswhere.com",
    "wss://relay.orangepill.dev",
    "wss://relay.nostrati.com",
];

#[derive(Parser, Debug)]
#[command(name = "nostr-publisher-template")]
#[command(about = "Publish and verify a Nostr text note with nostr-sdk 0.44.1")]
struct Args {
    /// Text note to publish
    #[arg(short, long)]
    content: String,

    /// Signing key in nsec or hex format; overrides NOSTR_NSEC
    #[arg(long)]
    secret_key: Option<String>,

    /// Relay URLs to publish to; repeatable. Overrides NOSTR_RELAYS if provided.
    #[arg(short, long)]
    relay: Vec<String>,

    /// Use the full expanded relay set instead of the shorter default set.
    #[arg(long)]
    all_relays: bool,

    /// Enable post-publication verification by event id
    #[arg(long, default_value_t = true)]
    verify: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    dotenvy::dotenv().ok();
    let args = Args::parse();

    let relay_urls = collect_relays(&args)?;

    let secret_key = args
        .secret_key
        .as_deref()
        .map(ToOwned::to_owned)
        .or_else(|| std::env::var("NOSTR_NSEC").ok())
        .context("missing signing key: pass --secret-key or set NOSTR_NSEC")?;

    let keys = Keys::parse(&secret_key)?;
    let client = Client::new(keys);

    for relay in &relay_urls {
        client
            .add_relay(relay)
            .await
            .with_context(|| format!("failed to add relay {relay}"))?;
    }

    client.connect().await;

    let builder = EventBuilder::text_note(args.content);
    let output = client
        .send_event_builder(builder)
        .await
        .context("failed to publish event")?;

    println!("event_id: {}", output.id());
    println!("sent_to: {:?}", output.success);
    println!("failed_to: {:?}", output.failed);

    if args.verify {
        let events = client
            .fetch_events(Filter::new().id(*output.id()), Duration::from_secs(10))
            .await
            .context("verification fetch failed")?;

        if events.is_empty() {
            println!("verification: not found yet on configured relays");
        } else {
            println!("verification: found {} event(s)", events.len());
        }
    }

    Ok(())
}

fn collect_relays(args: &Args) -> Result<Vec<String>> {
    let mut relays = Vec::new();

    relays.extend(args.relay.iter().filter_map(|relay| normalize_relay(relay)));

    if let Ok(value) = std::env::var("NOSTR_RELAYS") {
        relays.extend(
            value
                .split(',')
                .filter_map(normalize_relay),
        );
    }

    relays.extend(DEFAULT_PRIMARY_RELAYS.iter().filter_map(|relay| normalize_relay(relay)));
    relays.extend(DEFAULT_SECONDARY_RELAYS.iter().filter_map(|relay| normalize_relay(relay)));
    if args.all_relays {
        relays.extend(DEFAULT_EXPANSION_RELAYS.iter().filter_map(|relay| normalize_relay(relay)));
    }

    dedupe(relays)
}

fn normalize_relay(input: &str) -> Option<String> {
    let trimmed = input.trim();
    if trimmed.is_empty() {
        return None;
    }

    Some(trimmed.trim_end_matches('/').to_string())
}

fn dedupe(relays: Vec<String>) -> Result<Vec<String>> {
    let mut seen = std::collections::BTreeSet::new();
    let mut out = Vec::new();

    for relay in relays {
        if seen.insert(relay.clone()) {
            out.push(relay);
        }
    }

    if out.is_empty() {
        anyhow::bail!("missing relays: pass --relay, set NOSTR_RELAYS, or use the embedded defaults");
    }

    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_relay_trims_whitespace_and_trailing_slash() {
        assert_eq!(normalize_relay("  wss://relay.damus.io/  "), Some("wss://relay.damus.io".to_string()));
        assert_eq!(normalize_relay("   "), None);
    }

    #[test]
    fn dedupe_preserves_first_seen_order() {
        let relays = vec![
            "wss://relay.one".to_string(),
            "wss://relay.two".to_string(),
            "wss://relay.one".to_string(),
            "wss://relay.three".to_string(),
        ];

        let out = dedupe(relays).unwrap();
        assert_eq!(out, vec![
            "wss://relay.one".to_string(),
            "wss://relay.two".to_string(),
            "wss://relay.three".to_string(),
        ]);
    }

    #[test]
    fn dedupe_rejects_empty_list() {
        let err = dedupe(vec![]).unwrap_err();
        assert!(err.to_string().contains("missing relays"));
    }
}
