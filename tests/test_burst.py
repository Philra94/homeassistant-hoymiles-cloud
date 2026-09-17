"""Deterministic burst scheduling, source selection, and outage regression tests."""
import asyncio
from datetime import datetime, timezone

import pytest

from tests.module_loader import load_integration_module

burst = load_integration_module('burst')
api_module = load_integration_module('hoymiles_api')
NOW = datetime(2026, 9, 17, 12, tzinfo=timezone.utc).timestamp()


def station(two=False):
    micros = {'a': {'sn': 'inverter-a', 'rule': {'port': 2}}}
    if two:
        micros['b'] = {'sn': 'inverter-b', 'rule': {'port': 4}}
    return {'station_info': {'timezone': {'name': 'Europe/Berlin'}},
            'devices': {'microinverters': micros}}


class Clock:
    value = 100.

    def __call__(self):
        return self.value


class API:
    def __init__(self):
        self.calls = []
        self.station = {'con': 1, 'dly': 2000, 'power': {'pv': 900}}
        self.inverters = {'con': 1, 'dly': 3000, 'mis': [
            {'sn': 'inverter-b', 'pac': 600, 'p1': 301, 'p2': 302, 'p3': 303, 'p4': 304},
            {'sn': 'inverter-a', 'pac': 300, 'p1': 101, 'p2': 102},
        ]}

    async def get_burst_data(self, sid, *, serials=None):
        self.calls.append((sid, serials))
        value = self.inverters if serials else self.station
        if isinstance(value, Exception):
            raise value
        return value


def setup(two=False):
    clock, api = Clock(), API()
    stations = {'one': station(two)}
    publishes, reauths = [], []
    poller = burst.BurstPoller(api, lambda: stations, lambda: publishes.append(True),
                              lambda: reauths.append(True), clock=clock, wall_clock=lambda: NOW)
    return poller, api, clock, stations, publishes, reauths


@pytest.mark.parametrize('raw,expected', [(0, 0.), ('4.2', 4.2), (None, None), ('-', None),
                                          (True, None), (-1, None), (float('inf'), None), (float('nan'), None)])
def test_watts_are_never_invented(raw, expected):
    assert burst.number(raw) == expected


@pytest.mark.parametrize('delay,expected', [(2000, 2), (0, 10), (None, 10), (-1, 10),
                                           ('1500', 1.5), (900, 1.5), (60000, 60), (float('inf'), 10)])
def test_server_delay_is_respected(delay, expected):
    assert burst.poll_delay({'dly': delay}) == expected


def test_independent_station_and_inverter_cadence_and_serial_routing():
    async def run():
        poller, api, clock, stations, _, _ = setup(two=True)
        assert await poller.poll_once('one') == 2
        data = {**stations['one'], 'burst': dict(poller.samples['one'])}
        assert burst.select_power(data, 'pv_power', now=clock()) == (True, 900)
        assert burst.select_power(data, 'pv_power', serial='inverter-a', port=2, now=clock()) == (True, 102)
        assert burst.select_power(data, 'pv_power', serial='inverter-b', port=2, now=clock()) == (True, 302)
        assert burst.select_channel_power(data, 2, now=clock()) == (False, None)
        clock.value += 2
        await poller.poll_once('one')
        assert len(api.calls) == 3 and api.calls[-1][1] is None
        clock.value += 1
        await poller.poll_once('one')
        assert len(api.calls) == 4 and api.calls[-1][1] == ['inverter-a', 'inverter-b']
    asyncio.run(run())


def test_single_inverter_preserves_station_channel_mapping():
    async def run():
        poller, _, clock, stations, _, _ = setup()
        await poller.poll_once('one')
        data = {**stations['one'], 'burst': poller.samples['one']}
        assert burst.select_channel_power(data, 2, now=clock()) == (True, 102)
        assert burst.select_channel_power(data, 3, now=clock()) == (False, None)
    asyncio.run(run())


def test_partial_payload_preserves_zero_and_missing_is_unknown():
    async def run():
        poller, api, clock, stations, _, _ = setup()
        api.station = {'con': 1, 'power': {'pv': 0, 'sp': 999}}
        api.inverters = {'con': 1, 'mis': [{'sn': 'inverter-a', 'p1': 0}]}
        await poller.poll_once('one')
        data = {**stations['one'], 'burst': poller.samples['one']}
        assert burst.select_power(data, 'pv_power', now=clock()) == (True, 0)
        assert burst.select_power(data, 'ev_charger_power', now=clock()) == (False, None)
        assert burst.select_channel_power(data, 1, now=clock()) == (True, 0)
        assert burst.select_channel_power(data, 2, now=clock()) == (True, None)
        assert burst.select_power(data, 'pv_power', serial='inverter-a', now=clock()) == (True, None)
    asyncio.run(run())


def test_disconnect_never_resurrects_slow_power_even_after_network_failure():
    async def run():
        poller, api, clock, stations, _, _ = setup()
        api.station = {'con': 0, 'power': {'pv': 12}}
        await poller.poll_once('one')
        api.station = RuntimeError('private URL must not be logged')
        clock.value += 20
        await poller.poll_once('one')
        data = {**stations['one'], 'burst': poller.samples['one']}
        assert burst.select_power(data, 'pv_power', now=clock()) == (True, None)
        api.station = {'con': 1, 'power': {'pv': 45}}
        clock.value += 20
        await poller.poll_once('one')
        assert burst.select_power(data, 'pv_power', now=clock()) == (True, 45)
    asyncio.run(run())


def test_inverter_errors_back_off_without_delaying_station_totals():
    async def run():
        poller, api, clock, stations, _, _ = setup()
        api.inverters = RuntimeError('unsupported')
        for _ in range(10):
            delay = await poller.poll_once('one')
            assert delay <= 2
            clock.value += 2
        assert len([call for call in api.calls if call[1]]) == 2
        assert len([call for call in api.calls if call[1] is None]) == 10
        data = {**stations['one'], 'burst': poller.samples['one']}
        assert burst.select_power(data, 'pv_power', now=clock()) == (True, 900)
        assert burst.select_channel_power(data, 1, now=clock()) == (False, None)
    asyncio.run(run())


def test_known_old_timestamp_and_nonadvancing_timestamp_are_stale():
    async def run():
        poller, api, clock, stations, _, _ = setup()
        api.station = {'con': 1, 'dly': 2000, 't': '2026-09-17 13:00:00', 'power': {'pv': 99}}
        await poller.poll_once('one')
        data = {**stations['one'], 'burst': poller.samples['one']}
        assert burst.select_power(data, 'pv_power', now=clock()) == (True, None)
        # Even without timezone metadata, a frozen vendor timestamp eventually expires.
        stations['one']['station_info'] = {}
        clock.value += 60
        await poller.poll_once('one')
        assert poller.samples['one']['station'].state == 'stale'
        api.station = {**api.station, 't': '2026-09-17 14:00:01'}
        clock.value += 20
        await poller.poll_once('one')
        assert poller.samples['one']['station'].state == 'live'
    asyncio.run(run())


def test_auth_failure_stops_all_loops_and_requests_reauth_once():
    async def run():
        poller, api, _, _, _, reauths = setup()
        api.station = api_module.LiveDataAuthError('denied')
        await poller.poll_once('one')
        await poller.poll_once('one')
        assert reauths == [True]
        assert poller.samples == {}
        assert len(api.calls) == 1
    asyncio.run(run())


def test_stop_cancels_inflight_requests_without_publishing_after_unload():
    async def run():
        poller, api, _, _, publishes, _ = setup()
        started = asyncio.Event()
        cancelled = asyncio.Event()
        async def hanging(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        api.get_burst_data = hanging
        poller.start()
        poller.start()  # Idempotent; no duplicate loop.
        assert len(poller._tasks) == 1
        await started.wait()
        await poller.stop()
        assert cancelled.is_set()
        assert not poller._tasks and not publishes
    asyncio.run(run())


def test_inventory_without_serial_or_port_does_not_guess():
    assert burst.inverter_targets({'devices': {'microinverters': {'a': {'id': 4, 'rule': {'port': 2}}}}}) == {}
    assert burst.inverter_targets({'devices': {'microinverters': {'a': {'sn': 'A', 'rule': {'port': True}}}}}) == {'A': 0}


def test_expiry_publishes_unavailable_without_waiting_for_network():
    async def run():
        poller, _, clock, stations, publishes, _ = setup()
        await poller.poll_once('one')
        count = len(publishes)
        clock.value += 31
        poller.expire()
        data = {**stations['one'], 'burst': poller.samples['one']}
        assert burst.select_power(data, 'pv_power', now=clock()) == (True, None)
        assert len(publishes) == count + 1
        poller.expire()
        assert len(publishes) == count + 1
    asyncio.run(run())


def test_string_total_requires_every_known_port_and_never_uses_ac_power():
    async def run():
        poller, api, clock, stations, _, _ = setup()
        await poller.poll_once('one')
        data = {**stations['one'], 'burst': poller.samples['one']}
        assert burst.select_power(data, 'pv_string_power', now=clock()) == (True, 203)
        api.inverters = {'con': 1, 'mis': [{'sn': 'inverter-a', 'pac': 300, 'p1': 101}]}
        clock.value += 10
        await poller.poll_once('one')
        assert burst.select_power(data, 'pv_string_power', now=clock()) == (True, None)
    asyncio.run(run())


def test_auth_failure_cannot_be_undone_by_another_inflight_station():
    async def run():
        poller, api, _, stations, _, reauths = setup()
        stations['two'] = station()
        started, release = asyncio.Event(), asyncio.Event()
        async def read(sid, **kwargs):
            if sid == 'one':
                started.set()
                await release.wait()
                return {'con': 1, 'power': {'pv': 999}}
            raise api_module.LiveDataAuthError('denied')
        api.get_burst_data = read
        pending = asyncio.create_task(poller.poll_once('one'))
        await started.wait()
        await poller.poll_once('two')
        release.set()
        await pending
        assert poller.samples == {} and reauths == [True]
    asyncio.run(run())
