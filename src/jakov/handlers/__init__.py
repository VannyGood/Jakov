from aiogram import Router


def all_routers() -> list[Router]:
    """In priority order: start's Cancel handlers must win over waiting-state handlers."""
    from jakov.handlers import channels, errors, membership, settings, start

    return [start.router, channels.router, settings.router, membership.router, errors.router]
