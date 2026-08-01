# Deployment saga — 2026-05-25 → 2026-06-01

Picking up here after the system restart. The retry loop on the Mac is dead (it was a `nohup`'d process — system reboot kills it). All file-on-disk state is intact. This doc is your re-entry point.

---

## TL;DR

- **HF Space is the working public deploy.** Reranker disabled (`RERANKER_DISABLED=1`), warm queries ~0.35s, BM25/cosine ranking quality only. Live at <https://hassannjb-sunnah-toolkit.hf.space>. README has a "Try it live" section pointing there (uncommitted — `git diff README.md`).
- **Oracle A1 in Toronto is effectively impossible right now.** Automated retry loop ran for 4 days, ~747 attempts, zero capacity windows. Past the 48h cutoff we agreed on. Time to pivot.
- **Open decision** when you come back: which path to take for "production-quality" deploy (reranker enabled). Three real options, ranked: 2015 MBP / Hetzner CX22 ARM / keep Oracle running passively.

---

## Where each piece stands

### HF Space (working, deprioritized)
- URL: <https://hassannjb-sunnah-toolkit.hf.space>
- Free CPU tier, 2 vCPU
- Reranker forced off via Space Variable `RERANKER_DISABLED=1` (set 2026-05-25)
- Warm queries: ~0.35 s. Cold start after ~48 h idle: 30–60 s.
- Ranking is BM25/cosine only, no cross-encoder reranking. Quality is "okay" for keyword queries, worse for conceptual ones.
- Other Space Variables: `MKL_NUM_THREADS=2`, `TORCH_NUM_THREADS=2`. (`OMP_NUM_THREADS` is HF-reserved.)
- `ANTHROPIC_API_KEY` not configured → natural-language search falls back to plain semantic results with `"fallback": "llm_unavailable"`. Adding it later would unlock the NL router.
- README update is uncommitted: a "Try it live" section pointing at the Space + documenting the reranker-disabled trade-off.

### Oracle A1 (stuck)
- Toronto region (`ca-toronto-1`), single AD (`KnBQ:CA-TORONTO-1-AD-1`)
- OCI CLI fully set up on your Mac:
  - `oci-cli` 3.84.0 via Homebrew
  - Config at `~/.oci/config` (chmod 600)
  - API keypair at `~/.oci/oci_api_key.pem`, fingerprint `70:d9:a9:76:09:a0:48:c5:39:1a:82:bd:de:22:93:4a`
  - Public key already uploaded to your OCI user profile under API Keys
- Retry script at `~/oracle-a1-retry.sh` — full `oci compute instance launch` call with all params filled in, retries on capacity + transient network errors, bails on unrecognized errors. Already de-bugged through two iterations (v1 bailed on a transient timeout, v2 doesn't).
- Log at `~/oracle-a1-retry.log` — 747 attempts as of 2026-06-02 03:14 UTC, all "Out of host capacity" or "connection timed out" (which v2 correctly treats as transient). Zero successes, zero unknown-error bailouts.
- The loop dies when you reboot. You can restart it after reboot with: `nohup ~/oracle-a1-retry.sh >> ~/oracle-a1-retry.log 2>&1 & disown`
- Blocker for actually using A1 even if it lands: GHCR image is `linux/amd64` only. Need to add `linux/arm64` to `.github/workflows/build-image.yml` and tag a new release before the VM can pull anything.

### OCIDs (saved so we don't re-fetch)
```
tenancy/compartment: ocid1.tenancy.oc1..aaaaaaaakos5usck6sd2pz5faie3lncysdj64cdnbs2avk2bxdc3gakndroq
availability domain: KnBQ:CA-TORONTO-1-AD-1
ubuntu 22.04 arm:    ocid1.image.oc1.ca-toronto-1.aaaaaaaagk36zqpdwaek52myplqwsk4hqdcvzcdqaya6pq6yh7pruypv6ooq
subnet (in use):     ocid1.subnet.oc1.ca-toronto-1.aaaaaaaaqpno47wti2v5c7wibazbrfpmtz4b7hqfq75qccor6zdzfzf3uvlq
                     (in vcn-20260526-1437, TCP/22 already open from 0.0.0.0/0)
unused VCN:          vcn-20260526-1436 (leftover from console-form attempts; clean up later)
SSH pubkey:          ~/.ssh/oracle_a1.pub (ed25519)
```

---

## The decision facing you (read this when you're back)

The original goal: a public-ish deploy that runs the **cross-encoder reranker** so search quality is closer to what you see locally on the M2 Air. HF can't carry the reranker on free CPU. Oracle was Plan A but is capacity-locked. So:

### Option A — 2015 MacBook Pro at home (Recommended)

Why it might actually be the best move:
- **It's x86_64.** Existing `ghcr.io/hassannjb/sunnah-toolkit:v1.1` is `linux/amd64`. Pull → run. No multi-arch build needed.
- **Skip brew entirely.** Install Docker Desktop (one .dmg). All the Python/PyTorch/transformers chain lives inside the Linux container. brew is the slow part on old macOS — Docker bypasses it.
- **You already know cloudflared** — same pattern as the M2 Air quick-tunnel deploy from 2026-05-22.
- **Free, your hardware, no cloud lottery.**

Honest latency expectation: **5–20 s per query** with reranker enabled. Slower than your M2 (no MPS, older Intel, smaller caches) but interactive. Way better than HF's BM25-only fallback.

**Pre-flight checks** before committing:
1. macOS version on the 2015 MBP. Docker Desktop needs 11+ (Big Sur). If on Catalina or older, you need Colima instead (lighter Docker alternative).
2. Sustained-load thermal behaviour. Fans will get loud during query bursts. Fine for a hobby demo, but not silent.

**Steps when you decide to go this route:**
1. Boot the 2015 MBP, check `sw_vers` — confirm macOS 11+
2. Download Docker Desktop for Mac (Intel): <https://docs.docker.com/desktop/install/mac-install/>
3. `docker pull ghcr.io/hassannjb/sunnah-toolkit:v1.1`
4. `docker run -d --restart unless-stopped -p 8000:8000 --name sunnah ghcr.io/hassannjb/sunnah-toolkit:v1.1`
5. Verify locally: `curl localhost:8000/healthz` and `curl 'localhost:8000/v1/search?query=mercy&limit=2'`
6. Quick tunnel for first test: `cloudflared tunnel --url http://localhost:8000`
7. Note the `*.trycloudflare.com` URL, share for smoke test
8. (Later) Named tunnel on a real domain for a stable URL

Total time if everything works: 15–20 min. If Docker Desktop installation hits a wall, you'll know within minutes.

### Option B — Hetzner CX22 ARM (€4.59/mo)

If the 2015 MBP doesn't pan out or you don't want fan noise:
- 4 vCPU / 8 GB RAM ARM, EU-located
- Billed hourly — you can spin it up to test, kill it if it doesn't work
- Same arm64 multi-arch story applies. You'd still need to add `linux/arm64` to the GHCR workflow.
- Otherwise identical to the Oracle plan: Ubuntu + Docker + cloudflared
- This is the "I want a real server and I'm willing to pay €5/mo" answer

### Option C — Stay on HF, accept BM25-only

Zero work, $0/mo, queries are sub-second. Search quality is what it is. Document the trade-off and move on. Defensible if your priority is getting other features (eval-set curation, lookup bug fix follow-ups) done rather than perfecting search quality on a public deploy.

### Option D — Keep Oracle retry running passively

Cost: zero. Just restart the loop after reboot. If you land an A1 instance someday, great — migrate to it then. In the meantime, don't block on it.

### My recommendation when you're back

**Restart the Oracle loop (5 seconds of work) + try Option A on the 2015 MBP tonight.** They don't compete. The MBP gives you a real "Try it live with reranker" link, the Oracle loop runs as lottery in the background.

---

## Other things worth knowing before you re-enter

- **The lookup bug fix (`get_hadith` keying on `hadith_number` vs `id_in_book`)** was merged 2026-05-29 — that's the `db62b35` HEAD. Unblocks eval-set labelling work. See [[lookup-bug-fix]] memory.
- **Eval-set curation is paused** waiting on a hadith expert. Batch-1 draft is at `docs/eval/curation-batch1-draft.md`. Don't restart this without the expert.
- **Reranker comparison is provisional** (bge-v2-m3, threshold 0.5) — needs re-running against clean labels once curation is done.

---

## How to restart the Oracle retry loop after reboot

```bash
nohup ~/oracle-a1-retry.sh >> ~/oracle-a1-retry.log 2>&1 &
disown
ps -ef | grep oracle-a1-retry | grep -v grep    # confirm it's alive
tail -f ~/oracle-a1-retry.log                    # watch attempts
```

If you decide to stop trying entirely, just don't restart it. The log + script stay on disk for evidence.
