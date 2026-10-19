"""The bot and cities: each club runs on its city's clock (the Monday digest
at 10 its time, DMs only in the daytime where the member is), theatre choices
put the club's first and label other cities', and `city:` asks about another."""
import asyncio
from datetime import datetime

from helpers import patch_bot_api


def run(coro):
    return asyncio.run(coro)


def test_other_cities_theatres_are_labelled():
    patch_bot_api()
    from features import shared
    shared._cities.update(short={'dc': 'DC', 'testville': 'TV'})
    got = {'multi': True, 'theatres': [
        {'name': 'AFI Silver Theatre', 'slug': 'afi', 'city': 'dc', 'yours': True},
        {'name': 'Testville House', 'slug': 'tv-house', 'city': 'testville', 'yours': False}]}

    async def fetch():
        return got
    shared.fetch_theatres, real = fetch, shared.fetch_theatres
    try:
        names = [c.name for c in run(shared.theatre_choices(''))]
        assert names == ['AFI Silver Theatre', 'Testville House (TV)']
        got['multi'] = False                                                   # one city: no labels
        assert [c.name for c in run(shared.theatre_choices('house'))] == ['Testville House']
    finally:
        shared.fetch_theatres = real


def test_the_digest_goes_out_at_ten_on_each_clubs_clock(monkeypatch):
    patch_bot_api()
    from features import alerts
    clocks = {1: datetime(2026, 10, 19, 10, 0), 2: datetime(2026, 10, 19, 9, 0)}    # a Monday; club 2 an hour behind
    posted = []

    async def post(channel, tag_watchers=False):
        posted.append((alerts.club(), tag_watchers))
        return True
    monkeypatch.setattr(alerts, 'connected_clubs', lambda: [(1, 900), (2, 777)])
    monkeypatch.setattr(alerts, 'club_now', lambda gid: clocks[gid])
    monkeypatch.setattr(alerts, 'channel_for', lambda gid: object())
    monkeypatch.setattr(alerts, 'post_digest', post)
    run(alerts.digest_loop.coro())
    assert posted == [(1, True)]
    clocks[2] = datetime(2026, 10, 19, 10, 0)                                         # an hour later, its turn
    clocks[1] = datetime(2026, 10, 19, 11, 0)
    run(alerts.digest_loop.coro())
    assert posted == [(1, True), (2, True)]


def test_dms_wait_for_daytime_where_the_member_is(monkeypatch):
    patch_bot_api()
    from features import alerts
    hours = {'America/New_York': 9, 'America/Chicago': 12}
    monkeypatch.setattr(alerts, 'zone_now', lambda tz: datetime(2026, 10, 19, hours[tz]))
    assert not alerts.awake({'tz': 'America/New_York'}, alerts.ASK_HOURS)              # 9 AM: too early to ask
    assert alerts.awake({'tz': 'America/Chicago'}, alerts.ASK_HOURS)
    assert alerts.awake({'tz': 'America/New_York'}, alerts.ALERT_HOURS)                # alerts from 8


def test_city_asks_about_another_city():
    patch_bot_api()
    from features import shared
    shared.use_club(1)
    shared._servers[900].update(city='dc', tz='America/New_York')
    assert shared.where_args() == {'group_id': 1, 'city': 'dc'}
    assert shared.where_args('dc') == {'group_id': 1, 'city': 'dc'}                  # its own city: the club
    assert shared.where_args('testville') == {'city': 'testville'}                   # another: that city's public view
    assert shared.club_zone(1).key == 'America/New_York'
