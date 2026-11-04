
import os
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

load_dotenv()

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]

SESSION = Path(
    os.getenv(
        "TELETHON_SESSION_PATH",
        "data/sessions/hypervault"
    )
)

SESSION.parent.mkdir(parents=True, exist_ok=True)


async def main():
    print("Connecting to Telegram...")

    async with TelegramClient(
        str(SESSION), API_ID, API_HASH
    ) as client:

        print("\nYour Telegram groups:\n")

        found = False

        async for dialog in client.iter_dialogs():
            if not dialog.is_group:
                continue

            print(f"{dialog.name}: {dialog.id}")

            if dialog.name.strip().casefold() == "hyper vault":
                found = True
                print("\n✅ HYPER VAULT FOUND!")
                print(f"Group ID: {dialog.id}")

                print("\nRecent files:")

                count = 0

                async for message in client.iter_messages(
                    dialog.entity, limit=100
                ):
                    if message.file:
                        print(
                            f"Message ID: {message.id} | "
                            f"File: {message.file.name or 'Unnamed'}"
                        )
                        count += 1

                print(f"\nFiles found in sample: {count}")

        if not found:
            print("\nHyper Vault was not found.")


if __name__ == "__main__":
    asyncio.run(main())
