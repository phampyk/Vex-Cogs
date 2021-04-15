import asyncio
import datetime
from typing import Optional

from discord.channel import TextChannel
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_list, humanize_timedelta

from status.commands.converters import ServiceConverter
from status.core.abc import MixinMeta
from status.objects import IncidentData, SendCache, Update
from status.updateloop import SendUpdate, process_json


class StatusCom(MixinMeta):

    # TODO: support DMs
    @commands.guild_only()
    @commands.cooldown(10, 120, commands.BucketType.user)
    @commands.command()
    async def status(self, ctx: commands.Context, service: ServiceConverter):
        """
        Check for incidents for a variety of services, eg Discord.

        **Available Services:**

        discord, github, zoom, reddit, epic_games, cloudflare, statuspage,
        python, twitter_api, oracle_cloud, twitter, digitalocean, sentry,
        geforcenow
        """
        if time_until := self.service_cooldown.handle(ctx.author.id, service.name):
            message = "Status updates for {} are on cooldown. Try again in {}.".format(
                service.friendly, humanize_timedelta(seconds=time_until)
            )
            return await ctx.send(message, delete_after=time_until)

        if restrictions := self.service_restrictions_cache.get_guild(
            ctx.guild.id, service.name  # type:ignore  # guild check
        ):
            channels = [self.bot.get_channel(channel) for channel in restrictions]
            channel_list = humanize_list(
                [channel.mention for channel in channels if isinstance(channel, TextChannel)],
                style="or",
            )
            if channel_list:
                return await ctx.send(
                    f"You can check updates for {service.friendly} in {channel_list}."
                )

        await ctx.trigger_typing()

        summary, etag, status = await self.statusapi.summary(service.id)

        if status != 200:
            return await ctx.send(f"Hmm, I can't get {service.friendly}'s status at the moment.")

        incidents_incidentdata_list = process_json(summary, "incidents")
        all_scheduled = process_json(summary, "scheduled")
        now = datetime.datetime.now(datetime.timezone.utc)
        scheduled_incidentdata_list = [
            i for i in all_scheduled if i.scheduled_for and i.scheduled_for < now
        ]  # only want ones happening

        to_send: Optional[IncidentData]
        other_incidents, other_scheduled = [], []
        if incidents_incidentdata_list:
            to_send = incidents_incidentdata_list[0]
            other_incidents = incidents_incidentdata_list[1:]
        elif scheduled_incidentdata_list:  # only want to send 1 thing
            to_send = scheduled_incidentdata_list[0]
            other_scheduled = scheduled_incidentdata_list[1:]
        else:
            to_send = None

        if not to_send:
            msg = "\N{WHITE HEAVY CHECK MARK} There are currently no live incidents."
            return await ctx.send(msg)

        update = Update(to_send, to_send.fields)
        await SendUpdate(
            self.bot,
            self.config_wrapper,
            update,
            service.name,
            SendCache(update, service.name),
            dispatch=False,
            force=True,
        ).send(
            {ctx.channel.id: {"mode": "all", "webhook": False, "edit_id": {}}},
        )
        await asyncio.sleep(0.2)

        msg = ""

        if other_incidents:
            msg += f"{len(other_incidents)} other incidents are live at the moment:\n"
            for incident in other_incidents:
                msg += f"{incident.title} (<{incident.link}>)\n"

        if other_scheduled:
            msg += (
                f"\n{len(other_scheduled)} other scheduled maintenance events are live at the "
                "moment:\n"
            )
            for incident in other_scheduled:
                msg += f"{incident.title} (<{incident.link}>)"

        if msg:
            await ctx.send(msg)
