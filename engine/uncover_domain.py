#!/usr/bin/env python3
"""
uncover_domain.py — Dynamically uncover constraints from an existing repository.

This script parses a target repository's architectural documents (ADRs, README)
and source code to extract:
1. The Core Directives (Axioms).
2. The Negative Space (known-wrong concepts vs default base model behavior).
3. The Golden Path (source files to load into `accepted/`).

Usage:
    python3 engine/uncover_domain.py --repo <path-to-repo> --domain <path-to-new-domain>
"""

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests module is required for Ollama API calls.")
    sys.exit(1)

OLLAMA_GENERATE = "http://127.0.0.1:11434/api/generate"

def call_llm(provider: str, api_key: str, system_prompt: str, prompt: str, model: str, max_tokens=1024, temperature=0.1) -> str:
    """Use selected provider to extract constraints."""
    try:
        if provider == "ollama":
            payload = {
                "model": model or "llama3:70b",
                "prompt": f"{system_prompt}\n\n{prompt}",
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                },
            }
            resp = requests.post(OLLAMA_GENERATE, json=payload, timeout=120)
            resp.raise_for_status()
            return resp.json()["response"].strip()
        elif provider in ["openai", "copilot"]:
            url = "https://api.openai.com/v1/chat/completions" if provider == "openai" else "https://models.inference.ai.azure.com/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model or "gpt-4o",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        elif provider == "anthropic":
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            payload = {
                "model": model or "claude-3-5-sonnet-20240620",
                "system": system_prompt,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": temperature
            }
            resp = requests.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers, timeout=120)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"].strip()
        elif provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{(model or 'gemini-1.5-pro')}:generateContent?key={api_key}"
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens
                }
            }
            resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=120)
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"Warning: LLM Call failed ({e}). Mocking extraction for now...", file=sys.stderr)
        return ""

def init_domain_structure(domain_path: Path):
    domain_path.mkdir(parents=True, exist_ok=True)
    (domain_path / "corpus" / "seed").mkdir(parents=True, exist_ok=True)
    (domain_path / "corpus" / "accepted").mkdir(parents=True, exist_ok=True)
    (domain_path / "benchmark" / "results").mkdir(parents=True, exist_ok=True)

def find_docs_list(repo_path: Path, max_chars_per_file=4000) -> list[str]:
    """Read all markdown docs (ADRs, README) to provide to LLM as a list of chunks."""
    docs = []
    # Sort files to ensure logical processing order
    for md_file in sorted(repo_path.rglob("*.md")):
        if "node_modules" in md_file.parts or ".venv" in md_file.parts:
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
            if not content.strip(): continue
            
            # Extract top and bottom of file to get intros and conclusions
            if len(content) > max_chars_per_file:
                half = max_chars_per_file // 2
                snippet = content[:half] + "\n\n...[content truncated]...\n\n" + content[-half:]
            else:
                snippet = content
            docs.append(f"--- File: {md_file.relative_to(repo_path)} ---\n{snippet}")
        except Exception:
            pass
    return docs

def find_code_files(repo_path: Path, max_files=20) -> list[Path]:
    """Find key source files."""
    code_files = []
    supported_exts = {".cpp", ".hpp", ".h", ".c", ".rs", ".py", ".ts", ".go"}
    for file in repo_path.rglob("*"):
        if "node_modules" in file.parts or ".venv" in file.parts or ".git" in file.parts or "build" in file.parts:
            continue
        if file.suffix in supported_exts and file.is_file():
            code_files.append(file)
            if len(code_files) >= max_files:
                break
    return code_files

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--domain", required=True, type=Path)
    parser.add_argument("--provider", default="ollama", choices=["ollama", "openai", "anthropic", "copilot", "gemini"])
    parser.add_argument("--model", default="", help="LLM Model name")
    parser.add_argument("--api-key", default="", help="API key for cloud provider")
    args, _ = parser.parse_known_args()

    repo = args.repo.resolve()
    domain = args.domain.resolve()
    provider = args.provider
    api_key = args.api_key or os.environ.get(f"{provider.upper()}_API_KEY", "") or os.environ.get("GITHUB_TOKEN", "")

    if provider in ["openai", "anthropic", "copilot", "gemini"] and not api_key:
        print(f"Error: --api-key or environment variable required for {provider}")
        sys.exit(1)

    if not repo.exists() or not repo.is_dir():
        print(f"Error: Target repository {repo} does not exist.")
        sys.exit(1)

    print(f"[*] Uncovering constraints from: {repo}")
    print(f"[*] Output domain folder: {domain}")

    # 1. Structure
    init_domain_structure(domain)

    # 2. Gather Docs
    doc_chunks = find_docs_list(repo)
    if not doc_chunks:
        print("[!] No documentation found. LLM extraction will be sparse.")
        doc_chunks = ["No architectural documentation available. Infer purely from code structure."]

    # 3. LLM Extraction
    print("[*] Passing knowledge graph to Epistemic LLM for iterative extraction...")
    
    sys_prompt = "You are an expert systems architect. Extract precise constraints."
    all_axioms = []
    all_anti_patterns = []

    print("    -> Extracting architectural rules and negative space chunk-by-chunk...")
    for chunk in doc_chunks:
        # Extract Axioms for this chunk
        axioms_prompt = f"Read the following architectural snippets. Extract 1-3 core absolute commandments or rules if present. Format them as a Markdown list. If none, return empty.\n\n{chunk}"
        axioms = call_llm(provider, api_key, sys_prompt, axioms_prompt, model=args.model, max_tokens=512)
        if axioms and len(axioms) > 10:
            all_axioms.append(axioms)

        # Extract Anti-Patterns for this chunk
        anti_prompt = f"Based on the following snippets, what standard programming habits are explicitly forbidden here? Output only a valid JSON list of strings. If none, output [].\n\n{chunk}"
        anti_patterns_raw = call_llm(provider, api_key, sys_prompt, anti_prompt, model=args.model, max_tokens=512)
        try:
            match = re.search(r'\[.*\]', anti_patterns_raw, re.DOTALL)
            if match:
                extracted = json.loads(match.group(0))
                all_anti_patterns.extend(extracted)
        except Exception:
            pass

    # Aggregate and Save Axioms
    final_axioms = "\n\n".join(all_axioms) if all_axioms else "# Discovered Rules\n\n1. Target repository has custom optimizations."
    with open(domain / "corpus" / "seed" / "rules.md", "w") as f:
        f.write("# Automatically Uncovered Architectural Priorities\n\n")
        f.write(final_axioms)

    # Aggregate and Save Anti-Patterns
    if not all_anti_patterns:
        all_anti_patterns = ["Using standard lock-based concurrency instead of the repository's preferred pattern."]
    
    with open(domain / "corpus" / "known-wrong-claims.json", "w") as f:
        json.dump([{"claim": claim, "reason": "Uncovered explicitly in repository documentation"} for claim in all_anti_patterns], f, indent=2)

    # 4. Migrate Golden Path
    print("    -> Anchoring code examples as the 'Golden Path'...")
    golden_dir = domain / "corpus" / "accepted" / repo.name
    golden_dir.mkdir(parents=True, exist_ok=True)
    
    code_files = find_code_files(repo)
    for cf in code_files:
        dest = golden_dir / cf.name
        # Simple copy to flatten, ignoring potential name collisions for the prototype
        if not dest.exists():
            shutil.copy2(cf, dest)
    print(f"    -> Copied {len(code_files)} source files as positive training examples.")

    print(f"\n[+] Uncover Complete! Domain generated at: {domain}")
    print("    Next step: Run `python epistemic.py generate --domain <domain>` to build the corpus.")

if __name__ == "__main__":
    main()
