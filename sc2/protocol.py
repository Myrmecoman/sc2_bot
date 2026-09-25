from __future__ import annotations

import asyncio
import sys
from contextlib import suppress
from typing import overload

from aiohttp.client_ws import ClientWebSocketResponse
from loguru import logger

# pyre-fixme[21]
from s2clientprotocol import sc2api_pb2 as sc_pb
from s2clientprotocol.query_pb2 import RequestQuery
from sc2.data import Status


class ProtocolError(Exception):
    @property
    def is_game_over_error(self) -> bool:
        return self.args[0] in ["['Game has already ended']", "['Not supported if game has already ended']"]


class ConnectionAlreadyClosedError(ProtocolError):
    pass


class Protocol:
    def __init__(self, ws: ClientWebSocketResponse) -> None:
        """
        A class for communicating with an SCII application.
        :param ws: the websocket (type: aiohttp.ClientWebSocketResponse) used to communicate with a specific SCII app
        """
        assert ws
        self._ws: ClientWebSocketResponse = ws
        # pyre-fixme[11]
        self._status: Status | None = None

    async def __request(self, request: sc_pb.Request) -> sc_pb.Response:
        logger.debug(f"Sending request: {request!r}")
        try:
            await self._ws.send_bytes(request.SerializeToString())
        except TypeError as exc:
            logger.exception("Cannot send: Connection already closed.")
            raise ConnectionAlreadyClosedError("Connection already closed.") from exc
        logger.debug("Request sent")

        response = sc_pb.Response()
        try:
            response_bytes = await self._ws.receive_bytes()
        except TypeError as exc:
            if self._status == Status.ended:
                logger.info("Cannot receive: Game has already ended.")
                raise ConnectionAlreadyClosedError("Game has already ended") from exc
            logger.error("Cannot receive: Connection already closed.")
            raise ConnectionAlreadyClosedError("Connection already closed.") from exc
        except asyncio.CancelledError:
            # If request is sent, the response must be received before reraising cancel
            try:
                await self._ws.receive_bytes()
            except asyncio.CancelledError:
                logger.critical("Requests must not be cancelled multiple times")
                sys.exit(2)
            raise

        response.ParseFromString(response_bytes)
        logger.debug("Response received")
        return response

    @overload
    async def _execute(self, create_game: sc_pb.RequestCreateGame) -> sc_pb.Response: ...
    @overload
    async def _execute(self, join_game: sc_pb.RequestJoinGame) -> sc_pb.Response: ...
    @overload
    async def _execute(self, restart_game: sc_pb.RequestRestartGame) -> sc_pb.Response: ...
    @overload
    async def _execute(self, start_replay: sc_pb.RequestStartReplay) -> sc_pb.Response: ...
    @overload
    async def _execute(self, leave_game: sc_pb.RequestLeaveGame) -> sc_pb.Response: ...
    @overload
    async def _execute(self, quick_save: sc_pb.RequestQuickSave) -> sc_pb.Response: ...
    @overload
    async def _execute(self, quick_load: sc_pb.RequestQuickLoad) -> sc_pb.Response: ...
    @overload
    async def _execute(self, quit: sc_pb.RequestQuit) -> sc_pb.Response: ...
    @overload
    async def _execute(self, game_info: sc_pb.RequestGameInfo) -> sc_pb.Response: ...
    @overload
    async def _execute(self, action: sc_pb.RequestAction) -> sc_pb.Response: ...
    @overload
    async def _execute(self, observation: sc_pb.RequestObservation) -> sc_pb.Response: ...
    @overload
    async def _execute(self, obs_action: sc_pb.RequestObserverAction) -> sc_pb.Response: ...
    @overload
    async def _execute(self, step: sc_pb.RequestStep) -> sc_pb.Response: ...
    @overload
    async def _execute(self, data: sc_pb.RequestData) -> sc_pb.Response: ...
    @overload
    async def _execute(self, query: RequestQuery) -> sc_pb.Response: ...
    @overload
    async def _execute(self, save_replay: sc_pb.RequestSaveReplay) -> sc_pb.Response: ...
    @overload
    async def _execute(self, map_command: sc_pb.RequestMapCommand) -> sc_pb.Response: ...
    @overload
    async def _execute(self, replay_info: sc_pb.RequestReplayInfo) -> sc_pb.Response: ...
    @overload
    async def _execute(self, available_maps: sc_pb.RequestAvailableMaps) -> sc_pb.Response: ...
    @overload
    async def _execute(self, save_map: sc_pb.RequestSaveMap) -> sc_pb.Response: ...
    @overload
    async def _execute(self, ping: sc_pb.RequestPing) -> sc_pb.Response: ...
    @overload
    async def _execute(self, debug: sc_pb.RequestDebug) -> sc_pb.Response: ...
    async def _execute(self, **kwargs) -> sc_pb.Response:
        assert len(kwargs) == 1, "Only one request allowed by the API"

        response: sc_pb.Response = await self.__request(sc_pb.Request(**kwargs))

        new_status = Status(response.status)
        if new_status != self._status:
            logger.info(f"Client status changed to {new_status} (was {self._status})")
        self._status = new_status

        if response.error:
            logger.debug(f"Response contained an error: {response.error}")
            raise ProtocolError(f"{response.error}")

        return response

    async def ping(self):
        result = await self._execute(ping=sc_pb.RequestPing())
        return result

    async def quit(self) -> None:
        with suppress(ConnectionAlreadyClosedError, ConnectionResetError):
            await self._execute(quit=sc_pb.RequestQuit())
