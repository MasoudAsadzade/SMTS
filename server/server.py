#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import optparse
import threading
import json
import framework
import net
import sys
import client
import logging
import enum
import traceback
import random
import pathlib
import time
import re
import sqlite3

__author__ = 'Matteo Marescotti'


class Config:
    port = 3000
    portfolio_max = 0  # 0 if no limit
    portfolio_min = 0  # 0 if no limit
    partition_timeout = None  # None if no partitioning
    partition_policy = [2, 2]  #
    solving_timeout = None  # None no timeout
    lemma_amount = None  # None for auto
    log_level = logging.INFO  #
    incremental = 2  # 0: always restart. 1: only push. 2: always incremental
    z3_path = pathlib.Path()
    fixedpoint_partition = False

    @staticmethod
    def entrust(node, header, solver, solvers):
        pass

    def __init__(self):
        self._z3 = None

    @property
    def z3(self):
        if self._z3:
            return self._z3
        try:
            sys.path.insert(0, str(self.z3_path.resolve()))
            self._z3 = __import__('z3')
        except:
            raise Exception('cannot import z3')
        return self.z3


class Tree(framework.AndNode):
    class Type(enum.Enum):
        standard = 0
        fixedpoint = 1

    def __init__(self,
                 smtlib: str,
                 name: str,
                 timeout: int,
                 z3,
                 *,
                 conn: sqlite3.Connection = None,
                 table_prefix: str = '',
                 fixedpoint_partition=True):
        self.name = name
        self.timeout = timeout
        self.conn = conn
        self.table_prefix = table_prefix
        if self.conn:
            self.conn.cursor().execute("CREATE TABLE IF NOT EXISTS {}SolvingHistory ("
                                       "id INTEGER NOT NULL PRIMARY KEY, "
                                       "ts INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),"
                                       "name TEXT NOT NULL, "
                                       "node TEXT, "
                                       "event TEXT NOT NULL, "
                                       "solver TEXT, "
                                       "data TEXT"
                                       ");".format(self.table_prefix))
            self.conn.commit()
        self.started = None

        c = z3.Context()
        f = z3.Fixedpoint(ctx=c)
        queries = f.parse_string(smtlib)
        if not queries:
            super().__init__(smtlib.split('(check-sat)')[0], '(check-sat)')
            self.type = self.Type.standard
        else:
            self.type = self.Type.fixedpoint
            query = queries[0]
            if not fixedpoint_partition:
                s = f.to_string([])
                super().__init__(s[s.index('(declare-rel '):], '(query ' + query.sexpr() + ')')
            else:
                _f = z3.Fixedpoint(ctx=c)
                queries = []
                for rule in f.get_rules():
                    if z3.is_quantifier(rule):
                        imp = rule.body()
                        body = imp.arg(0)
                        if imp.num_args() == 2:  # if is implies
                            head = imp.arg(1)
                            if z3.is_and(body):
                                for i in range(body.num_args()):  # app always before others
                                    ch = body.arg(i)
                                    if z3.is_app(ch) and ch.decl().kind() == z3.Z3_OP_UNINTERPRETED:
                                        _f.register_relation(ch.decl())
                                    else:
                                        break
                            else:
                                _f.register_relation(body.decl())
                            if head.eq(query):
                                head = z3.Bool(query.sexpr() + str(len(queries)), c)
                                queries.append(head)
                            _f.register_relation(head.decl())
                            _f.add_rule(head, body)
                            continue
                    else:
                        imp = rule
                    _f.register_relation(imp.decl())
                    _f.add_rule(rule)

                s = _f.to_string([])

                super().__init__(s[s.index('(declare-rel '):], '')

                node = framework.OrNode(self)
                self._db_log(self, 'OR', '', node.path())
                for query in queries:
                    child = framework.AndNode('',
                                              '(query ' + query.sexpr() + ')',
                                              node)
                    self._db_log(node, 'AND', '', {"node": child.path(), "query": query.sexpr()})

    @property
    def is_timeout(self):
        return (self.started + self.timeout) < time.time() if self.started else False

    def to_string(self, node, start=None):
        npop = 0
        if start:
            while not start.is_ancestor(node):
                if isinstance(start, framework.AndNode):
                    npop += 1
                start = start.parent
        smtlibs = []

        while node is not start:
            if isinstance(node, framework.AndNode):
                smtlibs.append(node.smtlib)
                if self.type is self.Type.standard and node is not self.root:
                    smtlibs.append('(push 1)')
            node = node.parent
        if self.type is self.Type.standard:
            smtlibs += ['(pop 1)' for _ in range(npop)]
        smtlibs.reverse()
        return '\n'.join(smtlibs)

    def db_log(self, solver, event, data=None):
        if solver.node.root is not self:
            raise ValueError('solver solving a different tree')
        self._db_log(solver.node, event, str(solver.remote_address), data)

    def _db_log(self, node, event, solver, data):
        if not self.conn:
            return
        self.conn.cursor().execute("INSERT INTO {}SolvingHistory (name, node, event, solver, data) "
                                   "VALUES (?,?,?,?,?)".format(self.table_prefix), (
                                       self.name,
                                       str(node.path()),
                                       event,
                                       solver,
                                       json.dumps(data) if data else None
                                   ))
        self.conn.commit()


class LemmaServer(net.Socket):
    def __init__(self, sock: net.Socket, listening: str):
        super().__init__(sock._sock)
        self.listening = listening

    def __repr__(self):
        return '<LemmaServer listening:{}>'.format(self.listening)

    def clear_lemmas(self, node):
        self.write({'name': node.root.name, 'node': node.path(), 'lemmas': '0'}, '')


class Solver(net.Socket):
    def __init__(self, sock: net.Socket, name: str):
        super().__init__(sock._sock)
        self.name = name
        self.node = None
        self.started = None
        self.or_waiting = []

    def __repr__(self):
        return '<{} at{} {}>'.format(
            self.name,
            self.remote_address,
            self.node.root.name + str(self.node.path()) if self.node else 'idle'
        )

    def solve(self, node: framework.AndNode, header: dict):
        if not isinstance(node.root, Tree):
            raise TypeError('node root of type Tree is expected')
        if self.node is not None:
            self.stop()
        if not node.query:
            return
        self.node = node
        header.update({
            'command': 'solve',
            'name': self.node.root.name,
            'node': self.node.path(),
            'query': self.node.query,
        })
        self.write(header, self.node.root.to_string(self.node))
        self.started = time.time()
        if not self.node.root.started:
            self.node.root.started = self.started
        self.node.root.db_log(self, '+')

    def incremental(self, node: framework.AndNode):
        header = {'command': 'incremental',
                  'name': self.node.root.name,
                  'node': self.node.path(),
                  'node_': node.path(),
                  'query': node.query,
                  }
        self.write(header, node.root.to_string(node, self.node))
        self.started = time.time()
        self.node = node

    def stop(self):
        if self.node is None:
            raise ValueError('not solving anything')
        self.write({
            'command': 'stop',
            'name': self.node.root.name,
            'node': self.node.path()
        }, '')
        self.node.root.db_log(self, '-')
        self.node = None
        self.or_waiting = []

    def set_lemma_server(self, lemma_server: LemmaServer = None):
        self.write({
            'command': 'lemmas',
            'lemmas': lemma_server.listening if lemma_server else ''
        }, '')

    def ask_partitions(self, n, node=None):
        if self.node is None:
            raise ValueError('not solving anything')
        self.write({
            'command': 'partition',
            'name': self.node.root.name,
            'node': self.node.path(),
            'partitions': n
        }, '')
        if not node:
            node = framework.OrNode(self.node)
        self.or_waiting.append(node)
        self.node.root.db_log(self, 'OR', node.path())

    def read(self):
        header, payload = super().read()
        if 'report' not in header:
            return {}, b''
        if header['report'] == 'partitions' and self.or_waiting:
            for node in self.or_waiting:
                if self.node.child(json.loads(header['node'])) is node.parent:
                    self.or_waiting.remove(node)
                    try:
                        for partition in payload.decode().split('\0'):
                            if len(partition) == 0:
                                continue
                            child = framework.AndNode('(assert {})'.format(partition),
                                                      node.parent.query,
                                                      node)
                            self.node.root.db_log(self, 'AND', {"node": child.path(), "smtlib": partition})
                        # if there is only one partition then it is discarded
                        # I leave the or node without children
                        partitions = len(node.children)
                        if partitions == 1:
                            node.children.clear()
                    except BaseException as ex:
                        header['report'] = 'error:(server) error reading partitions: {}'.format(ex)
                        node.children.clear()
                        # ask them again?
                    else:
                        header['report'] = 'received ' + str(partitions) + ' partitions'
                    return header, payload

        if self.node is None:
            return header, payload

        if self.node.root.name != header['name'] or str(self.node.path()) != header['node']:
            return {}, b""

        if header['report'] in framework.SolveStatus.__members__:
            status = framework.SolveStatus.__members__[header['report']]
            self.node.root.db_log(self, 'STATUS', header)
            self.node.status = status
            if self.node.root.status != framework.SolveStatus.unknown:
                self.node.root.db_log(self, 'SOLVED', {'status': self.node.root.status.name})
            if status == framework.SolveStatus.unknown:
                self.stop()

        return header, payload


class ParallelizationServer(net.Server):
    def __init__(self,
                 config: Config,
                 *,
                 conn: sqlite3.Connection = None,
                 table_prefix: str = '',
                 logger: logging.Logger = None):
        super().__init__(port=config.port, timeout=1, logger=logger)
        self.config = config
        self.conn = conn
        self.table_prefix = table_prefix
        self.trees = set()
        self.current = None
        if self.conn:
            cursor = self.conn.cursor()
            cursor.execute("DROP TABLE IF EXISTS {}ServerLog;".format(table_prefix))
            cursor.execute("CREATE TABLE IF NOT EXISTS {}ServerLog ("
                           "id INTEGER NOT NULL PRIMARY KEY, "
                           "ts INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),"
                           "level TEXT NOT NULL,"
                           "message TEXT NOT NULL,"
                           "data TEXT"
                           ");".format(self.table_prefix))
            cursor.execute("DROP TABLE IF EXISTS {}SolvingHistory;".format(table_prefix))
            cursor.execute("VACUUM;")
            self.conn.commit()
        self.log(logging.INFO, 'server start')

    def handle_accept(self, sock):
        self.log(logging.DEBUG, 'new connection from {}'.format(sock.remote_address))

    def handle_message(self, sock, header, payload):
        self.log(logging.DEBUG, 'message from {}'.format(sock.remote_address),
                 {'header': header, 'payload': payload.decode()})
        if isinstance(sock, Solver):
            if not header:
                return
            if 'report' in header:
                try:
                    level, message = header['report'].split(':', 1)
                    level = logging._nameToLevel[level.upper()]
                except:
                    level = logging.INFO
                    message = header['report']
                self.log(level, '{}: {}'.format(sock, message), {'header': header, 'payload': payload.decode()})
            self.entrust()
            return
        if 'command' in header:
            if header['command'] == 'solve':
                if 'name' not in header:
                    return
                self.log(logging.INFO, 'new instance "{}"'.format(
                    header['name']
                ), {'header': header})
                try:
                    self.trees.add(
                        Tree(payload.decode(),
                             header['name'],
                             self.config.solving_timeout,
                             self.config.z3,
                             conn=self.conn,
                             table_prefix=self.table_prefix,
                             fixedpoint_partition=self.config.fixedpoint_partition)
                    )
                except BaseException as ex:
                    self.log(logging.ERROR, 'cannot add instance: ' + str(traceback.format_exc()))
                self.entrust()
        elif 'solver' in header:
            solver = Solver(sock, header['solver'])
            self.log(logging.INFO, 'new {}'.format(
                solver,
            ), {'header': header, 'payload': payload.decode()})
            self._rlist.remove(sock)
            self._rlist.add(solver)
            lemma_server = self.lemma_server
            if lemma_server:
                solver.set_lemma_server(lemma_server)
            self.entrust()
        elif 'lemmas' in header:
            if header['lemmas'][0] == ':':
                header['lemmas'] = sock.remote_address[0] + header['lemmas']
            lemma_server = self.lemma_server
            if lemma_server:
                lemma_server.close()
            self._rlist.remove(sock)
            lemma_server = LemmaServer(sock, header["lemmas"])
            self.log(logging.INFO, 'new {}'.format(
                lemma_server
            ), {'header': header, 'payload': payload.decode()})
            self._rlist.add(lemma_server)
            for solver in (solver for solver in self._rlist if isinstance(solver, Solver)):
                solver.set_lemma_server(lemma_server)
        elif 'eval' in header:
            response_payload = ''
            try:
                if header['eval']:
                    response_payload = str(eval(header['eval']))
            except:
                response_payload = str(traceback.format_exc())
            finally:
                sock.write({}, response_payload)

    def handle_close(self, sock):
        self.log(logging.INFO, 'connection closed by {}'.format(
            sock
        ))
        if isinstance(sock, Solver):
            for node in sock.or_waiting:
                if len(node.children) > 0:
                    continue
                try:
                    node.parent.children.remove(node)
                except ValueError:
                    self.log(logging.ERROR, '{} had bad pending or-node {}'.format(
                        sock,
                        node.path()
                    ))
        if isinstance(sock, LemmaServer):
            for solver in self.solvers(False):
                solver.set_lemma_server()

    def handle_timeout(self):
        self.entrust()

    def entrust(self):
        solving = self.current
        # if the current tree is already solved or timed out: stop it
        if self.current and self.current.started and (
                        self.current.status != framework.SolveStatus.unknown or self.current.is_timeout
        ):
            self.log(
                logging.INFO,
                '{} instance "{}" after {:.2f} seconds'.format(
                    'solved' if self.current.status != framework.SolveStatus.unknown else 'timeout',
                    self.current.name,
                    time.time() - self.current.started
                )
            )
            for solver in {solver for solver in self.solvers(True) if solver.node.root == self.current}:
                solver.stop()
            self.current = None
        if not self.current:
            schedulables = [root for root in self.trees if
                            root.status == framework.SolveStatus.unknown and not root.is_timeout]
            if schedulables:
                self.current = schedulables[0]
                self.log(logging.INFO, 'solving instance "{}"'.format(self.current.name))
        if solving != self.current and self.lemma_server:
            self.lemma_server.clear_lemmas(self.current)
        if not self.current:
            if solving is not None:
                self.log(logging.INFO, 'all done.')
            return

        assert isinstance(self.current, Tree)

        idle_solvers = self.solvers(None)
        nodes = self.current.all()
        nodes.sort()

        def level_children(level):
            return self.config.partition_policy[level % len(self.config.partition_policy)]

        def leaves():
            return (node for node in nodes if len(node.children) == 0 and isinstance(node, framework.AndNode))

        def internals():
            return (node for node in nodes if len(node.children) > 0 and isinstance(node, framework.AndNode))

        # stop the solvers working on an already solved node of the whole tree, and add them to the list
        for node in nodes:
            if node.status != framework.SolveStatus.unknown:
                for solver in self.solvers(node):
                    idle_solvers.add(solver)

        # spread the solvers among the unsolved nodes taking care of portfolio_max
        # first the leafs will be filled. inner nodes after and only if available solvers are left idle
        # nodes.reverse()
        for selection in [leaves, internals]:
            available = -1
            while available != len(idle_solvers):
                available = len(idle_solvers)
                for node in selection():
                    if node.status != framework.SolveStatus.unknown:
                        continue
                    try:
                        # here i check whether some node in the path to the root is already solved
                        # could happen that an upper level node is solved while one on its subtree is still unsolved
                        for _node in node.path(True):
                            if _node.status != framework.SolveStatus.unknown:
                                raise StopIteration
                    except StopIteration:
                        continue
                    if 0 < self.config.portfolio_max <= len(self.solvers(node)):
                        continue
                    # now node needs to be solved.
                    # try to search for a solver...
                    if not idle_solvers:
                        for _node in (node for node in internals() if
                                      len(node.children) == level_children(len(node.path()))):
                            # here I check that every or-node child has some partitions, that is
                            # every child is completed. if not then I'll not use any solver working on that node.
                            try:
                                for child in _node.children:
                                    if len(child.children) == 0:
                                        raise StopIteration
                            except StopIteration:
                                continue
                            solvers = self.solvers(_node)
                            if 0 <= self.config.portfolio_min < len(solvers):
                                try:
                                    # I can choose only one solver if it's solving for more than partition_timeout
                                    for solver in self.solvers(_node):
                                        if self.config.partition_timeout and solver.started + self.config.partition_timeout > time.time():
                                            continue
                                        idle_solvers.add(solver)
                                        raise StopIteration
                                except StopIteration:
                                    break

                    # if there are still no solvers available
                    if not idle_solvers:
                        continue

                    if self.current.type is Tree.Type.standard:
                        if self.config.incremental > 0:
                            try:
                                # I first search for a solver which is solving an ancestor of node
                                # so that incremental solving would work better
                                for solver in idle_solvers:
                                    if not solver.node or solver.node is node:
                                        continue
                                    if solver.node.is_ancestor(node):
                                        idle_solvers.remove(solver)
                                        solver.incremental(node)
                                        raise StopIteration
                            except StopIteration:
                                continue
                        if self.config.incremental > 1:
                            try:
                                # try to use incremental on another already solving solver
                                for solver in idle_solvers:
                                    if solver.node and solver.node is not node:
                                        idle_solvers.remove(solver)
                                        solver.incremental(node)
                                        raise StopIteration
                            except StopIteration:
                                continue

                    solver = idle_solvers.pop()
                    if solver.node is node:
                        continue
                    header = {}
                    if self.config.lemma_amount:
                        header["lemmas"] = self.config.lemma_amount
                    self.config.entrust(
                        node,
                        header,
                        solver,
                        {solver for solver in self.solvers(True) if solver.node.root == self.current}
                    )
                    solver.solve(node, header)

        # only standard instances can partition
        if self.current.type is not Tree.Type.standard:
            return

        # if need partition: ask partitions
        if (self.config.partition_timeout or idle_solvers):
            # for all the leafs with at least one solver
            for leaf in (leaf for leaf in leaves() if self.solvers(leaf)):
                max_children = level_children(leaf.level())
                for i in range(max_children - len(leaf.children)):
                    solvers = list(self.solvers(leaf))
                    random.shuffle(solvers)
                    for solver in solvers:
                        # ask the solver to partition if timeout or if needed because idle solvers
                        if idle_solvers or solver.started + self.config.partition_timeout <= time.time():
                            solver.ask_partitions(level_children(leaf.level() + 1))
                            break

    # node = False : return all solvers
    # node = True  : return all non idle solvers
    # node = None  : return all idle solvers
    def solvers(self, node):
        return {solver for solver in self._rlist
                if isinstance(solver, Solver) and (
                    node is False or
                    (node is True and solver.node is not None) or
                    solver.node == node
                )}

    @property
    def lemma_server(self) -> LemmaServer:
        lemmas = [sock for sock in self._rlist if isinstance(sock, LemmaServer)]
        if lemmas:
            return lemmas[0]

    def log(self, level, message, data=None):
        super().log(level, message)
        if not self.conn or level < self.config.log_level:
            return
        self.conn.cursor().execute("INSERT INTO {}ServerLog (level, message, data) "
                                   "VALUES (?,?,?)".format(self.table_prefix), (
                                       logging.getLevelName(level),
                                       message,
                                       json.dumps(data) if data else None
                                   ))
        self.conn.commit()


if __name__ == '__main__':
    def config_config(option, opt_str, value, parser):
        path = pathlib.Path(value)
        sys.path.insert(0, str(path.parent.absolute()))

        try:
            module = __import__(path.stem)
        except ImportError as ex:
            logging.log(logging.ERROR, str(ex))
            sys.exit(1)

        config = getattr(parser.values, option.dest)

        for i in dir(module):
            if i[:1] == "_":
                continue
            setattr(config, i, getattr(module, i))


    def config_database(option, opt_str, value, parser):
        try:
            conn = sqlite3.connect(value)
        except BaseException as ex:
            logging.log(logging.ERROR, str(ex))
            sys.exit(1)
        setattr(parser.values, option.dest, conn)


    parser = optparse.OptionParser()
    parser.add_option('-c', '--config', dest='config', type='str',
                      action="callback", callback=config_config,
                      default=Config(), help='config file path')
    parser.add_option('-d', '--database', dest='db', type='str',
                      action="callback", callback=config_database,
                      default=None, help='sqlite3 database file path')

    options, args = parser.parse_args()

    logging.basicConfig(level=options.config.log_level, format='%(asctime)s\t%(levelname)s\t%(message)s')

    server = ParallelizationServer(config=options.config, conn=options.db, logger=logging.getLogger('server'))
    if hasattr(options.config, 'files'):
        def send_files(address, files):
            for path in files:
                try:
                    client.send_file(address, path)
                except:
                    pass


        thread = threading.Thread(target=send_files, args=(server.address, options.config.files))
        thread.start()

    try:
        server.run_forever()
    except KeyboardInterrupt:
        pass
