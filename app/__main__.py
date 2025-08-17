"""CLI entry point"""
import click
import asyncio
from app.integrations.fec_client import FECClient
from app.integrations.states.api.wa_pdc import WAPDCClient
from app.utils.logging import setup_logging

setup_logging()

@click.group()
def cli():
    """Ampersand Candidate Tracker CLI"""
    pass

@cli.command()
def fec_backfill_initial():
    """Run initial FEC backfill"""
    asyncio.run(_fec_backfill())

@cli.command()
@click.option("--state", help="State to ingest (e.g., WA)")
def state_ingest(state):
    """Run state ingestion"""
    asyncio.run(_state_ingest(state))

async def _fec_backfill():
    client = FECClient()
    await client.backfill_initial()

async def _state_ingest(state_code):
    if state_code == "WA":
        client = WAPDCClient()
        await client.ingest_all()
    else:
        print(f"State {state_code} not implemented yet")

if __name__ == "__main__":
    cli()
