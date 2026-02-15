"""Entry point for the Galaxy Profile README generator."""

import argparse
import logging
import os
import sys

import requests
import yaml

from generator.config import ConfigError, validate_config
from generator.github_api import GitHubAPI
from generator.svg_builder import SVGBuilder

logger = logging.getLogger(__name__)

DEMO_STATS = {"commits": 1847, "stars": 342, "prs": 156, "issues": 89, "repos": 42}
DEMO_LANGUAGES = {
    "Python": 450000,
    "TypeScript": 380000,
    "JavaScript": 120000,
    "Go": 95000,
    "Rust": 45000,
    "Shell": 30000,
    "Dockerfile": 15000,
    "CSS": 10000,
}


def generate(args):
    """Generate SVGs from config (existing behavior extracted into a function)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    demo = getattr(args, "demo", False)

    # Load config
    if demo:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.example.yml")
    else:
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.yml")

    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
    except FileNotFoundError:
        if demo:
            logger.error("config.example.yml not found.")
        else:
            logger.error("config.yml not found. Copy config.example.yml to config.yml and edit it.")
        sys.exit(1)

    try:
        config = validate_config(config)
    except ConfigError as e:
        logger.error("Invalid config: %s", e)
        sys.exit(1)

    username = config["username"]
    additional_accounts = config.get("additional_accounts", [])
    organizations = config.get("organizations", [])
    all_accounts = [username] + additional_accounts

    if len(all_accounts) > 1 or organizations:
        extra_info = []
        if len(additional_accounts) > 0:
            extra_info.append(f"{len(additional_accounts)} additional account(s)")
        if len(organizations) > 0:
            extra_info.append(f"{len(organizations)} organization(s)")
        logger.info("Generating profile SVGs for @%s (+ %s)...", username, ", ".join(extra_info))
    else:
        logger.info("Generating profile SVGs for @%s...", username)

    if demo:
        logger.info("Demo mode: using hardcoded stats and languages.")
        stats = DEMO_STATS
        languages = DEMO_LANGUAGES
    else:
        # Fetch GitHub data from all accounts and aggregate
        stats = {"commits": 0, "stars": 0, "prs": 0, "issues": 0, "repos": 0}
        languages = {}

        # Get tokens for different accounts
        work_token = os.environ.get("GITHUB_WORK_TOKEN", "")
        
        # Fetch from user accounts
        for idx, account in enumerate(all_accounts, 1):
            logger.info("[%d/%d] Fetching data for @%s...", idx, len(all_accounts) + len(organizations), account)
            # Use work token for work account, default token for others
            token = work_token if account in additional_accounts else None
            api = GitHubAPI(account, token=token)

            try:
                account_stats = api.fetch_stats()
                # Aggregate stats
                for key in stats:
                    stats[key] += account_stats.get(key, 0)
                logger.info("  Stats: %s", account_stats)
            except (requests.exceptions.RequestException, ValueError, KeyError) as e:
                logger.warning("  Could not fetch stats for @%s (%s). Skipping.", account, e)

            try:
                account_languages = api.fetch_languages()
                # Aggregate languages by summing byte counts
                for lang, bytes_count in account_languages.items():
                    languages[lang] = languages.get(lang, 0) + bytes_count
                logger.info("  Languages: %d found", len(account_languages))
            except (requests.exceptions.RequestException, ValueError, KeyError) as e:
                logger.warning("  Could not fetch languages for @%s (%s). Skipping.", account, e)
        
        # Fetch contributions to organizations
        if organizations:
            # Use the work account (adornetejr-wex) for org access since it's a member
            # If no additional accounts, fall back to primary account
            org_account = additional_accounts[0] if additional_accounts else username
            api = GitHubAPI(org_account, token=work_token)
            logger.info("Using account @%s for organization queries", org_account)
            
            for idx, org in enumerate(organizations, len(all_accounts) + 1):
                logger.info("[%d/%d] Fetching contributions to org %s...", idx, len(all_accounts) + len(organizations), org)
                try:
                    org_stats = api.fetch_org_contributions(org)
                    # Aggregate org contributions
                    for key in stats:
                        stats[key] += org_stats.get(key, 0)
                    logger.info("  Contributions: %s", org_stats)
                except (requests.exceptions.RequestException, ValueError, KeyError) as e:
                    logger.warning("  Could not fetch org contributions for %s (%s). Skipping.", org, e)
                
                # Fetch languages from org repos where user contributed
                try:
                    org_languages = api.fetch_org_languages(org)
                    # Aggregate languages
                    for lang, bytes_count in org_languages.items():
                        languages[lang] = languages.get(lang, 0) + bytes_count
                    logger.info("  Languages: %d found", len(org_languages))
                except (requests.exceptions.RequestException, ValueError, KeyError) as e:
                    logger.warning("  Could not fetch org languages for %s (%s). Skipping.", org, e)

    # Merge manual languages from config if specified
    if "languages" in config and "manual" in config["languages"]:
        manual_langs = config["languages"]["manual"]
        logger.info("Adding %d manual languages from config", len(manual_langs))
        for lang, bytes_count in manual_langs.items():
            languages[lang] = languages.get(lang, 0) + bytes_count

    logger.info("Aggregated Stats: %s", stats)
    logger.info("Total Languages: %d found", len(languages))

    # Build SVGs
    builder = SVGBuilder(config, stats, languages)
    output_dir = os.path.join(os.path.dirname(__file__), "..", "assets", "generated")
    os.makedirs(output_dir, exist_ok=True)

    svgs = {
        "galaxy-header.svg": builder.render_galaxy_header(),
        "stats-card.svg": builder.render_stats_card(),
        "tech-stack.svg": builder.render_tech_stack(),
        "projects-constellation.svg": builder.render_projects_constellation(),
    }

    for filename, content in svgs.items():
        path = os.path.join(output_dir, filename)
        with open(path, "w") as f:
            f.write(content)
        logger.info("Wrote %s", path)

    logger.info("Done! 4 SVGs generated.")


def main():
    parser = argparse.ArgumentParser(description="Generate Galaxy Profile SVGs")
    subparsers = parser.add_subparsers(dest="command")

    # Subcommand: init
    subparsers.add_parser("init", help="Interactive setup wizard to create config.yml")

    # Subcommand: generate
    gen_parser = subparsers.add_parser("generate", help="Generate SVGs from config")
    gen_parser.add_argument(
        "--demo",
        action="store_true",
        help="Generate SVGs with demo data (no API calls, uses config.example.yml)",
    )

    # Top-level --demo for backward compatibility (python -m generator.main --demo)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Generate SVGs with demo data (no API calls, uses config.example.yml)",
    )

    args = parser.parse_args()

    if args.command == "init":
        from generator.cli_init import run_init
        run_init()
    else:
        # Default behavior: generate (supports both `generate --demo` and `--demo`)
        generate(args)


if __name__ == "__main__":
    main()
