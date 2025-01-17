import asyncio
import os
import os as _os
import unittest
from asyncio.events import AbstractEventLoop
from functools import wraps
from types import ModuleType
from typing import Any, Iterable, List, Optional, Union
from unittest import SkipTest, expectedFailure, skip, skipIf, skipUnless

from tortoise import Model, Tortoise
from tortoise.backends.base.config_generator import generate_config as _generate_config
from tortoise.exceptions import DBConnectionError
from tortoise.transactions import current_transaction_map

__all__ = (
    "SimpleTestCase",
    "TestCase",
    "TruncationTestCase",
    "IsolatedTestCase",
    "getDBConfig",
    "requireCapability",
    "env_initializer",
    "initializer",
    "finalizer",
    "SkipTest",
    "expectedFailure",
    "skip",
    "skipIf",
    "skipUnless",
)
_TORTOISE_TEST_DB = "sqlite://:memory:"
# pylint: disable=W0201

expectedFailure.__doc__ = """
Mark test as expecting failiure.

On success it will be marked as unexpected success.
"""

_CONFIG: dict = {}
_CONNECTIONS: dict = {}
_SELECTOR = None
_LOOP: AbstractEventLoop = None  # type: ignore
_MODULES: Iterable[Union[str, ModuleType]] = []
_CONN_MAP: dict = {}


def getDBConfig(app_label: str, modules: Iterable[Union[str, ModuleType]]) -> dict:
    """
    DB Config factory, for use in testing.

    :param app_label: Label of the app (must be distinct for multiple apps).
    :param modules: List of modules to look for models in.
    """
    return _generate_config(
        _TORTOISE_TEST_DB,
        app_modules={app_label: modules},
        testing=True,
        connection_label=app_label,
    )


async def _init_db(config: dict) -> None:
    try:
        await Tortoise.init(config)
        await Tortoise._drop_databases()
    except DBConnectionError:  # pragma: nocoverage
        pass

    await Tortoise.init(config, _create_db=True)
    await Tortoise.generate_schemas(safe=False)


def _restore_default() -> None:
    Tortoise.apps = {}
    Tortoise._connections = _CONNECTIONS.copy()
    current_transaction_map.update(_CONN_MAP)
    Tortoise._init_apps(_CONFIG["apps"])
    Tortoise._inited = True


def initializer(
    modules: Iterable[Union[str, ModuleType]],
    db_url: Optional[str] = None,
    app_label: str = "models",
    loop: Optional[AbstractEventLoop] = None,
) -> None:
    """
    Sets up the DB for testing. Must be called as part of test environment setup.

    :param modules: List of modules to look for models in.
    :param db_url: The db_url, defaults to ``sqlite://:memory``.
    :param app_label: The name of the APP to initialise the modules in, defaults to "models"
    :param loop: Optional event loop.
    """
    # pylint: disable=W0603
    global _CONFIG
    global _CONNECTIONS
    global _SELECTOR
    global _LOOP
    global _TORTOISE_TEST_DB
    global _MODULES
    global _CONN_MAP
    _MODULES = modules
    if db_url is not None:  # pragma: nobranch
        _TORTOISE_TEST_DB = db_url
    _CONFIG = getDBConfig(app_label=app_label, modules=_MODULES)

    loop = loop or asyncio.get_event_loop()
    _LOOP = loop
    _SELECTOR = loop._selector  # type: ignore
    loop.run_until_complete(_init_db(_CONFIG))
    _CONNECTIONS = Tortoise._connections.copy()
    _CONN_MAP = current_transaction_map.copy()
    Tortoise.apps = {}
    Tortoise._connections = {}
    Tortoise._inited = False


def finalizer() -> None:
    """
    Cleans up the DB after testing. Must be called as part of the test environment teardown.
    """
    _restore_default()
    loop = _LOOP
    loop._selector = _SELECTOR  # type: ignore
    loop.run_until_complete(Tortoise._drop_databases())


def env_initializer() -> None:  # pragma: nocoverage
    """
    Calls ``initializer()`` with parameters mapped from environment variables.

    ``TORTOISE_TEST_MODULES``:
        A comma-separated list of modules to include *(required)*
    ``TORTOISE_TEST_APP``:
        The name of the APP to initialise the modules in *(optional)*

        If not provided, it will default to "models".
    ``TORTOISE_TEST_DB``:
        The db_url of the test db. *(optional*)

        If not provided, it will default to an in-memory SQLite DB.
    """
    modules = str(_os.environ.get("TORTOISE_TEST_MODULES", "tests.testmodels")).split(",")
    db_url = _os.environ.get("TORTOISE_TEST_DB", "sqlite://:memory:")
    app_label = _os.environ.get("TORTOISE_TEST_APP", "models")
    if not modules:  # pragma: nocoverage
        raise Exception("TORTOISE_TEST_MODULES envvar not defined")
    initializer(modules, db_url=db_url, app_label=app_label)


class SimpleTestCase(unittest.IsolatedAsyncioTestCase):
    """
    The Tortoise base test class.

    This will ensure that your DB environment has a test double set up for use.

    An asyncio capable test class that provides some helper functions.

    Will run any ``test_*()`` function either as sync or async, depending
    on the signature of the function.
    If you specify ``async test_*()`` then it will run it in an event loop.

    Based on `asynctest <http://asynctest.readthedocs.io/>`_
    """

    async def _setUpDB(self) -> None:
        pass

    async def _tearDownDB(self) -> None:
        pass

    def _setupAsyncioLoop(self):
        loop = asyncio.get_event_loop()
        loop.set_debug(True)
        self._asyncioTestLoop = loop
        fut = loop.create_future()
        self._asyncioCallsTask = loop.create_task(self._asyncioLoopRunner(fut))  # type: ignore
        loop.run_until_complete(fut)

    def _tearDownAsyncioLoop(self):
        loop = self._asyncioTestLoop
        self._asyncioTestLoop = None  # type: ignore
        self._asyncioCallsQueue.put_nowait(None)  # type: ignore
        loop.run_until_complete(self._asyncioCallsQueue.join())  # type: ignore

    async def asyncSetUp(self) -> None:
        await self._setUpDB()

    async def asyncTearDown(self) -> None:
        await self._tearDownDB()
        Tortoise.apps = {}
        Tortoise._connections = {}
        Tortoise._inited = False

    def assertListSortEqual(
        self, list1: List[Any], list2: List[Any], msg: Any = ..., sorted_key: Optional[str] = None
    ) -> None:
        if isinstance(list1[0], Model):
            super().assertListEqual(
                sorted(list1, key=lambda x: x.pk), sorted(list2, key=lambda x: x.pk), msg=msg
            )
        elif isinstance(list1[0], dict) and sorted_key:
            super().assertListEqual(
                sorted(list1, key=lambda x: x[sorted_key]),
                sorted(list2, key=lambda x: x[sorted_key]),
                msg=msg,
            )
        else:
            super().assertListEqual(sorted(list1), sorted(list2), msg=msg)


class IsolatedTestCase(SimpleTestCase):
    """
    An asyncio capable test class that will ensure that an isolated test db
    is available for each test.

    Use this if your test needs perfect isolation.

    Note to use ``{}`` as a string-replacement parameter, for your DB_URL.
    That will create a randomised database name.

    It will create and destroy a new DB instance for every test.
    This is obviously slow, but guarantees a fresh DB.

    If you define a ``tortoise_test_modules`` list, it overrides the DB setup module for the tests.
    """

    tortoise_test_modules: Iterable[Union[str, ModuleType]] = []

    async def _setUpDB(self) -> None:
        config = getDBConfig(app_label="models", modules=self.tortoise_test_modules or _MODULES)
        await Tortoise.init(config, _create_db=True)
        await Tortoise.generate_schemas(safe=False)
        self._connections = Tortoise._connections.copy()

    async def _tearDownDB(self) -> None:
        Tortoise._connections = self._connections.copy()
        await Tortoise._drop_databases()


class TruncationTestCase(SimpleTestCase):
    """
    An asyncio capable test class that will truncate the tables after a test.

    Use this when your tests contain transactions.

    This is slower than ``TestCase`` but faster than ``IsolatedTestCase``.
    Note that usage of this does not guarantee that auto-number-pks will be reset to 1.
    """

    async def _setUpDB(self) -> None:
        await super(TruncationTestCase, self)._setUpDB()
        _restore_default()

    async def _tearDownDB(self) -> None:
        _restore_default()
        # TODO: This is a naive implementation: Will fail to clear M2M and non-cascade foreign keys
        for app in Tortoise.apps.values():
            for model in app.values():
                quote_char = model._meta.db.query_class._builder().QUOTE_CHAR
                await model._meta.db.execute_script(  # nosec
                    f"DELETE FROM {quote_char}{model._meta.db_table}{quote_char}"
                )
        await super(TruncationTestCase, self)._tearDownDB()


class TransactionTestContext:
    __slots__ = ("connection", "connection_name", "token")

    def __init__(self, connection) -> None:
        self.connection = connection
        self.connection_name = connection.connection_name

    async def __aenter__(self):
        current_transaction = current_transaction_map[self.connection_name]
        self.token = current_transaction.set(self.connection)
        if hasattr(self.connection, "_parent"):
            self.connection._connection = await self.connection._parent._pool.acquire()
        await self.connection.start()
        return self.connection

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.connection.rollback()
        if hasattr(self.connection, "_parent"):
            await self.connection._parent._pool.release(self.connection._connection)
        current_transaction_map[self.connection_name].reset(self.token)


class TestCase(TruncationTestCase):
    """
    An asyncio capable test class that will ensure that each test will be run at
    separate transaction that will rollback on finish.

    This is a fast test runner. Don't use it if your test uses transactions.
    """

    async def asyncSetUp(self) -> None:
        await super(TestCase, self).asyncSetUp()
        _restore_default()
        self.__db__ = Tortoise.get_connection("models")
        self.__transaction__ = TransactionTestContext(self.__db__._in_transaction().connection)
        await self.__transaction__.__aenter__()  # type: ignore

    async def asyncTearDown(self) -> None:
        await self.__transaction__.__aexit__(None, None, None)
        await super(TestCase, self).asyncTearDown()

    async def _setUpDB(self) -> None:
        await super(TestCase, self)._setUpDB()

    async def _tearDownDB(self) -> None:
        if self.__db__.capabilities.supports_transactions:
            _restore_default()
        else:
            await super()._tearDownDB()


def requireCapability(connection_name: str = "models", **conditions: Any):
    """
    Skip a test if the required capabilities are not matched.

    .. note::
        The database must be initialized *before* the decorated test runs.

    Usage:

    .. code-block:: python3

        @requireCapability(dialect='sqlite')
        async def test_run_sqlite_only(self):
            ...

    Or to conditionally skip a class:

    .. code-block:: python3

        @requireCapability(dialect='sqlite')
        class TestSqlite(test.TestCase):
            ...

    :param connection_name: name of the connection to retrieve capabilities from.
    :param conditions: capability tests which must all pass for the test to run.
    """

    def decorator(test_item):
        if not isinstance(test_item, type):

            @wraps(test_item)
            def skip_wrapper(*args, **kwargs):
                db = Tortoise.get_connection(connection_name)
                for key, val in conditions.items():
                    if getattr(db.capabilities, key) != val:
                        raise SkipTest(f"Capability {key} != {val}")
                return test_item(*args, **kwargs)

            return skip_wrapper

        # Assume a class is decorated
        funcs = {
            var: getattr(test_item, var)
            for var in dir(test_item)
            if var.startswith("test_") and callable(getattr(test_item, var))
        }
        for name, func in funcs.items():
            setattr(
                test_item,
                name,
                requireCapability(connection_name=connection_name, **conditions)(func),
            )

        return test_item

    return decorator
