import asyncio
import json
from logging import getLogger
from pathlib import Path
from typing import Dict, List, NamedTuple, Union

import aiohttp
import tabulate
from redbot.core import VersionInfo, commands
from redbot.core import version_info as cur_red_version
from redbot.core.utils.chat_formatting import box

from .consts import DOCS_BASE, GREEN_CIRCLE, RED_CIRCLE
from .loop import VexLoop

log = getLogger("red.vex-utils")


cog_ver_lock = asyncio.Lock()


def format_help(self: commands.Cog, ctx: commands.Context) -> str:
    """Wrapper for format_help_for_context. **Not** currently for use outside my cogs.

    Thanks Sinbad.

    Parameters
    ----------
    self : commands.Cog
        The Cog class
    context : commands.Context
        Context

    Returns
    -------
    str
        Formatted help
    """
    docs = DOCS_BASE.format(self.qualified_name.lower())
    pre_processed = super(type(self), self).format_help_for_context(ctx)  # type:ignore

    return (
        f"{pre_processed}\n\nAuthor: **`{self.__author__}`**\nCog Version: "  # type:ignore
        f"**`{self.__version__}`**\n{docs}"  # type:ignore
    )
    # adding docs link here so doesn't show up in auto generated docs


# TODO: stop using red internal util


async def format_info(
    ctx: commands.Context,
    qualified_name: str,
    cog_version: str,
    extras: Dict[str, Union[str, bool]] = {},
    loops: List[VexLoop] = [],
) -> str:
    """Generate simple info text about the cog. **Not** currently for use outside my cogs.

    Parameters
    ----------
    ctx : commands.Context
        Context
    qualified_name : str
        The name you want to show, eg "BetterUptime"
    cog_version : str
        The version of the cog
    extras : Dict[str, Union[str, bool]], optional
        Dict which is foramtted as key: value\\n. Bools as a value will be replaced with
        check/cross emojis, by default {}
    loops : List[VexLoop], optional
        List of VexLoops you want to show, by default []

    Returns
    -------
    str
        Simple info text.
    """
    cog_name = qualified_name.lower()
    current = _get_current_vers(cog_version, qualified_name)
    try:
        latest = await _get_latest_vers()

        cog_updated = current.cogs[cog_name] >= latest.cogs[cog_name]
        utils_updated = current.utils == latest.utils
        red_updated = current.red >= latest.red
    except Exception:  # anything and everything, eg aiohttp error or version parsing error
        log.warning("Unable to parse versions.", exc_info=True)
        cog_updated, utils_updated, red_updated = "Unknown", "Unknown", "Unknown"
        latest = UnknownVers({cog_name: "Unknown"})

    start = f"{qualified_name} by Vexed.\n<https://github.com/Vexed01/Vex-Cogs>\n\n"
    versions = [
        [
            "This Cog",
            current.cogs.get(cog_name),
            latest.cogs.get(cog_name),
            GREEN_CIRCLE if cog_updated else RED_CIRCLE,
        ],
        [
            "Bundled Utils",
            current.utils,
            latest.utils,
            GREEN_CIRCLE if utils_updated else RED_CIRCLE,
        ],
        [
            "Red",
            current.red,
            latest.red,
            GREEN_CIRCLE if red_updated else RED_CIRCLE,
        ],
    ]
    update_msg = "\n"
    if not cog_updated:
        update_msg += f"To update this cog, use the `{ctx.clean_prefix}cog update` command.\n"
    if not utils_updated:
        update_msg += (
            f"To update the bundled utils, use the `{ctx.clean_prefix}cog update` command.\n"
        )
    if not red_updated:
        update_msg += "To update Red, see https://docs.discord.red/en/stable/update_red.html\n"

    data = []
    if loops:
        for loop in loops:
            data.append([loop.friendly_name, GREEN_CIRCLE if loop.integrity else RED_CIRCLE])

    if extras:
        if data:
            data.append([])
        for key, value in extras.items():
            if isinstance(value, bool):
                str_value = GREEN_CIRCLE if value else RED_CIRCLE
            else:
                assert isinstance(value, str)
                str_value = value
            data.append([key, str_value])

    boxed = box(
        tabulate.tabulate(versions, headers=["", "Your Version", "Latest version", "Up to date?"])
    )
    boxed += update_msg
    if data:
        boxed += box(tabulate.tabulate(data, tablefmt="plain"))

    return f"{start}{boxed}"


async def out_of_date_check(cogname: str, currentver: str) -> None:
    """Send a log at warning level if the cog is out of date."""
    try:
        async with cog_ver_lock:
            vers = await _get_latest_vers()
        if VersionInfo.from_str(currentver) < vers.cogs[cogname]:
            log.warning(
                f"Your {cogname} cog, from Vex, is out of date. You can update your cogs with the "
                "'cog update' command in Discord."
            )
        else:
            log.debug(f"{cogname} cog is up to date")
    except Exception as e:
        log.debug(
            f"Something went wrong checking if {cogname} cog is up to date. See below.", exc_info=e
        )
        # really doesn't matter if this fails so fine with debug level
        return


class Vers(NamedTuple):
    cogs: Dict[str, VersionInfo]
    utils: str
    red: VersionInfo


class UnknownVers(NamedTuple):
    cogs: Dict[str, str]
    utils: str = "Unknown"
    red: str = "Unknown"


async def _get_latest_vers() -> Vers:
    data: dict
    async with aiohttp.ClientSession() as session:
        async with session.get("https://api.vexcodes.com/v1/vers/", timeout=5) as r:
            data = await r.json()
            latest_utils = data["utils"][:7]
            data.pop("utils")
            latest_cogs = data
        async with session.get("https://pypi.org/pypi/Red-DiscordBot/json", timeout=3) as r:
            data = await r.json()
            latest_red = VersionInfo.from_str(data.get("info", {}).get("version", "0.0.0"))

    obj_latest_cogs = {
        str(cogname): VersionInfo.from_str(ver) for cogname, ver in latest_cogs.items()
    }

    return Vers(obj_latest_cogs, latest_utils, latest_red)


def _get_current_vers(curr_cog_ver: str, qual_name: str) -> Vers:
    with open(Path(__file__).parent / "commit.json") as fp:
        data = json.load(fp)
        latest_utils = data.get("latest_commit", "Unknown")[:7]

    return Vers(
        {qual_name.lower(): VersionInfo.from_str(curr_cog_ver)},
        latest_utils,
        cur_red_version,
    )
