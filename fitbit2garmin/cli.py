import asyncio
import functools
import logging
import pathlib

from datetime import date

import click

from . import commands


class ClickDate(click.DateTime):
    name = "date"

    def convert(self, *args, **kwargs) -> date:
        return super().convert(*args, **kwargs).date()

    def __repr__(self) -> str:
        return "Date"


def async_main(func):
    @functools.wraps(func)
    def wrapper(**kwargs):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(func(**kwargs))

    return wrapper


@click.group()
def cli():
    pass


@cli.command(help="Create activities' tcx")
@click.option(
    "-c",
    "--cache-directory",
    type=click.Path(file_okay=True, path_type=pathlib.Path),
    default=".cache",
)
@click.option(
    "-d",
    "--directory",
    type=click.Path(file_okay=True, path_type=pathlib.Path),
    default="f2g",
)
@click.option("-s", "--start-date", type=ClickDate(formats=["%Y-%m-%d"]), required=True)
@click.option(
    "-e",
    "--end-date",
    type=ClickDate(formats=["%Y-%m-%d"]),
    default=str(date.today()),
)
@async_main
async def create_activity_tcx(
    cache_directory: pathlib.Path,
    directory: pathlib.Path,
    start_date: date,
    end_date: date,
):
    await commands.create_activity_tcx_or_fit(
        cache_directory, directory, start_date, end_date, True
    )


@cli.command(help="Create activities' fit")
@click.option(
    "-c",
    "--cache-directory",
    type=click.Path(file_okay=True, path_type=pathlib.Path),
    default=".cache",
)
@click.option(
    "-d",
    "--directory",
    type=click.Path(file_okay=True, path_type=pathlib.Path),
    default="f2g",
)
@click.option("-s", "--start-date", type=ClickDate(formats=["%Y-%m-%d"]), required=True)
@click.option(
    "-e",
    "--end-date",
    type=ClickDate(formats=["%Y-%m-%d"]),
    default=str(date.today()),
)
@async_main
async def create_activity_fit(
    cache_directory: pathlib.Path,
    directory: pathlib.Path,
    start_date: date,
    end_date: date,
):
    await commands.create_activity_tcx_or_fit(
        cache_directory, directory, start_date, end_date, False
    )


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    cli()


if __name__ == "__main__":
    run()
