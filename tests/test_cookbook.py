import contextlib
import functools
import opcode
import os
import sys
from logging import getLogger

import aspectlib
import pytest

import hunter
from hunter import CallPrinter
from hunter import CodePrinter
from hunter import VarsSnooper

logger = getLogger(__name__)


def nothin(x):
    return x


def bar():
    baz()


@nothin
@nothin
@nothin
@nothin
def baz():
    for i in range(10):
        os.path.join('a', str(i))
    foo = 1


def brief_probe(qualname, *actions, **kwargs):
    return aspectlib.weave(qualname, functools.partial(hunter.wrap, actions=actions, **kwargs))


def fast_probe(qualname, *actions, **filters):
    def tracing_decorator(func):
        @functools.wraps(func)
        def tracing_wrapper(*args, **kwargs):
            # create the Tracer manually to avoid spending time in likely useless things like:
            # - loading PYTHONHUNTERCONFIG
            # - setting up the clear_env_var or thread_support options
            # - atexit cleanup registration
            with hunter.Tracer().trace(hunter.When(hunter.Query(**filters), *actions)):
                return func(*args, **kwargs)

        return tracing_wrapper

    return aspectlib.weave(qualname, tracing_decorator)  # this does the monkeypatch


@contextlib.contextmanager
def no_probe(*args, **kwargs):
    yield


@pytest.mark.parametrize('impl', [fast_probe, brief_probe, no_probe])
def test_probe(impl, benchmark):
    with impl('%s.baz' % __name__, hunter.VarsPrinter('foo', stream=open(os.devnull, 'w')), kind="return", depth=0):
        benchmark(bar)


def error():
    raise RuntimeError()


def silenced1():
    try:
        error()
    except Exception:
        pass


def silenced2():
    try:
        error()
    except Exception as exc:
        print(exc)
        for i in range(25):
            print(i)
    return 'x'


def silenced3():
    try:
        error()
    finally:
        return "mwhahaha"


def silenced4():
    try:
        error()
    except Exception as exc:
        logger.info(repr(exc))


def notsilenced():
    try:
        error()
    except Exception as exc:
        raise ValueError(exc)


class DumpExceptions(hunter.CodePrinter):
    should_trace = False
    depth = 0
    count = 0

    def __call__(self, event):
        self.count += 1
        if event.kind == 'exception':  # something interesting happened ;)
            self.should_trace = True
            self.depth = event.depth
            self.count = 0
            self.output("{BRIGHT}{fore(BLUE)}{} tracing on exception: {}{RESET}\n",
                        ">" * 46, self.try_repr(event.arg[1]))
            super(DumpExceptions, self).__call__(event)
        elif self.should_trace:
            super(DumpExceptions, self).__call__(event)
            if event.kind == 'return':  # stop if function returned
                self.should_trace = False
                self.output("{BRIGHT}{fore(BLACK)}{} function exit{RESET}\n",
                            "-" * 46)
            elif event.depth > self.depth + 1:  # too many details
                return
            elif self.count > 10:  # bail out on too many lines
                self.should_trace = False
                self.output("{BRIGHT}{fore(BLACK)}{} too many lines{RESET}\n",
                            "-" * 46)


class DumpExceptions(hunter.CodePrinter):
    events = None
    depth = 0
    count = 0

    def __call__(self, event):
        self.count += 1
        if event.kind == 'exception':  # something interesting happened ;)
            self.events = [event.detach(lambda field, value: self.try_repr(value))]
            self.exc = self.try_repr(event.arg[1])
            self.depth = event.depth
            self.count = 0
        elif self.events:
            if event.kind == 'return':  # stop if function returned
                if event.arg or opcode.opname[event.code.co_code[event.frame.f_lasti]] == 'RETURN_VALUE':
                    self.output("{BRIGHT}{fore(BLUE)}{} trace of exception: {}{RESET}\n",
                                ">" * 46, self.exc)
                    for event in self.events:
                        super(DumpExceptions, self).__call__(event)
                    if self.count > 10:
                        self.output("{BRIGHT}{fore(BLACK)}{} too many lines{RESET}\n",
                                    "-" * 46)
                    else:
                        self.output("{BRIGHT}{fore(BLACK)}{} function exit{RESET}\n",
                                    "-" * 46)
                self.events = []
            elif event.depth > self.depth + 1:  # too many details
                return
            elif self.count < 10:
                self.events.append(event.detach())


def test_dump_exceptions():
    # print(DumpExceptions(
    #     force_colors=True
    # )(SimpleNamespace(
    #     kind='exception',
    #     depth=0,
    #     arg=[1, 2, 3],
    #     filename='foobar',
    #     lineno=123,
    #     tracer=SimpleNamespace(
    #         depth=1,
    #         threading_support=False
    #     )
    # )))
    with hunter.trace(stdlib=False, action=DumpExceptions(force_colors=1, stream=sys.stdout)):
        silenced1()
        silenced2()
        silenced3()
        silenced4()

        print("Done silenced")
        try:
            notsilenced()
            print("Done not silenced")
        except ValueError:
            pass


def test_examples():
    print("""
    CodePrinter
    """)
    with hunter.trace(stdlib=False, actions=[CodePrinter, VarsSnooper]):
        os.path.join(*map(str, range(10)))

    print("""
    CallPrinter
    """)
    with hunter.trace(stdlib=False, actions=[CallPrinter, VarsSnooper]):
        os.path.join(*map(str, range(10)))
