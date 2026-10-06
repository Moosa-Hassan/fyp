import asyncio
import logging


class RetryHelper:

    @staticmethod
    async def try_function(
        func,
        count: int = 5,
        logger=None,
    ):
        last_exception = None

        for i in range(count):
            try:
                return await func(last_exception)

            except Exception as ex:

                if i == count - 1:
                    log = logger or logging.getLogger("DatabaseAgentFactory")

                    log.warning(
                        "Failed to execute the function after %s attempts.",
                        count,
                        exc_info=ex,
                    )

                    raise

                last_exception = ex

                await asyncio.sleep(0.2)

        raise RuntimeError("Failed to execute the function.")