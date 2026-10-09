import asyncio

import pyopsy


@pyopsy.profiler
def normal_func(n):
    return sum(range(n))


@pyopsy.profiler
def normal_gen(n):
    for i in range(n):
        yield i * i


@pyopsy.profiler
async def async_func(n):
    await asyncio.sleep(0.0000001)
    return n * n


@pyopsy.profiler
async def async_gen(n):
    for i in range(n):
        await asyncio.sleep(0.0000001)
        yield i * i


@pyopsy.profiler(lines=True)
def hot(n):
    total = 0
    for index in range(n):
        total += index
    return total


async def main():
    print(await async_func(10))
    print(str(async_func))
    async for value in async_gen(5):
        print(value)
    print(str(async_gen))


with pyopsy.session(cli=True, log="pyopsy.jsonl"):
    print(normal_func(100000))
    print(str(normal_func))
    for value in normal_gen(5):
        print(value)
    print(str(normal_gen))
    print(hot(20000))
    print(str(hot))
    asyncio.run(main())
    input("The page is open. Press Enter to stop.\n")
