#!/usr/bin/env python
#coding=utf-8
"""
Copyright (c) 2006-2017 sqlmap developers (http://sqlmap.org/)
See the file 'doc/COPYING' for copying permission
"""

from lib.core.agent import agent
from lib.core.common import arrayizeValue
from lib.core.common import getLimitRange
from lib.core.common import isInferenceAvailable
from lib.core.common import isNoneValue
from lib.core.common import isNumPosStrValue
from lib.core.common import isTechniqueAvailable
from lib.core.common import safeSQLIdentificatorNaming
from lib.core.common import safeStringFormat
from lib.core.common import unArrayizeValue
from lib.core.common import unsafeSQLIdentificatorNaming
from lib.core.data import conf
from lib.core.data import kb
from lib.core.data import logger
from lib.core.data import queries
from lib.core.enums import CHARSET_TYPE
from lib.core.enums import DBMS
from lib.core.enums import EXPECTED
from lib.core.enums import PAYLOAD
from lib.core.exception import SqlmapNoneDataException
from lib.core.settings import CURRENT_DB
from lib.request import inject

from plugins.generic.enumeration import Enumeration as GenericEnumeration

class Enumeration(GenericEnumeration):
    def __init__(self):
        GenericEnumeration.__init__(self)

    def getPrivileges(self, *args):
        warnMsg = u"在Microsoft SQL Server上，无法获取数据库用户的权限，"
        warnMsg += u"sqlmap将检查数据库用户是否是数据库管理员"
        logger.warn(warnMsg)

        users = []
        areAdmins = set()

        if conf.user:
            users = [conf.user]
        elif not len(kb.data.cachedUsers):
            users = self.getUsers()
        else:
            users = kb.data.cachedUsers

        for user in users:
            user = unArrayizeValue(user)

            if user is None:
                continue

            isDba = self.isDba(user)

            if isDba is True:
                areAdmins.add(user)

            kb.data.cachedUsersPrivileges[user] = None

        return (kb.data.cachedUsersPrivileges, areAdmins)

    def getTables(self):
        if len(kb.data.cachedTables) > 0:
            return kb.data.cachedTables

        self.forceDbmsEnum()

        if conf.db == CURRENT_DB:
            conf.db = self.getCurrentDb()

        if conf.db:
            dbs = conf.db.split(',')
        else:
            dbs = self.getDbs()

        for db in dbs:
            dbs[dbs.index(db)] = safeSQLIdentificatorNaming(db)

        dbs = filter(None, dbs)

        infoMsg = u"获取数据库%s中的表: %s" % ("s" if len(dbs) > 1 else "", ", ".join(db if isinstance(db, basestring) else db[0] for db in sorted(dbs)))
        logger.info(infoMsg)

        rootQuery = queries[DBMS.MSSQL].tables

        if any(isTechniqueAvailable(_) for _ in (PAYLOAD.TECHNIQUE.UNION, PAYLOAD.TECHNIQUE.ERROR, PAYLOAD.TECHNIQUE.QUERY)) or conf.direct:
            for db in dbs:
                if conf.excludeSysDbs and db in self.excludeDbsList:
                    infoMsg = u"跳过系统数据库'%s'" % db
                    logger.info(infoMsg)

                    continue

                for query in (rootQuery.inband.query, rootQuery.inband.query2, rootQuery.inband.query3):
                    query = query.replace("%s", db)
                    value = inject.getValue(query, blind=False, time=False)
                    if not isNoneValue(value):
                        break

                if not isNoneValue(value):
                    value = filter(None, arrayizeValue(value))
                    value = [safeSQLIdentificatorNaming(unArrayizeValue(_), True) for _ in value]
                    kb.data.cachedTables[db] = value

        if not kb.data.cachedTables and isInferenceAvailable() and not conf.direct:
            for db in dbs:
                if conf.excludeSysDbs and db in self.excludeDbsList:
                    infoMsg = u"跳过系统数据库'%s'" % db
                    logger.info(infoMsg)

                    continue

                infoMsg = u"获取数据库'%s'的表数量" % db
                logger.info(infoMsg)

                for query in (rootQuery.blind.count, rootQuery.blind.count2, rootQuery.blind.count3):
                    _ = query.replace("%s", db)
                    count = inject.getValue(_, union=False, error=False, expected=EXPECTED.INT, charsetType=CHARSET_TYPE.DIGITS)
                    if not isNoneValue(count):
                        break

                if not isNumPosStrValue(count):
                    if count != 0:
                        warnMsg = "无法检索数据库'%s'的表数量" % db
                        logger.warn(warnMsg)
                    continue

                tables = []

                for index in xrange(int(count)):
                    _ = safeStringFormat((rootQuery.blind.query if query == rootQuery.blind.count else rootQuery.blind.query2 if query == rootQuery.blind.count2 else rootQuery.blind.query3).replace("%s", db), index)

                    table = inject.getValue(_, union=False, error=False)
                    if not isNoneValue(table):
                        kb.hintValue = table
                        table = safeSQLIdentificatorNaming(table, True)
                        tables.append(table)

                if tables:
                    kb.data.cachedTables[db] = tables
                else:
                    warnMsg = u"无法检索数据库'%s'中的表" % db
                    logger.warn(warnMsg)

        if not kb.data.cachedTables and not conf.search:
            errMsg = u"无法检索任何数据库的表"
            raise SqlmapNoneDataException(errMsg)
        else:
            for db, tables in kb.data.cachedTables.items():
                kb.data.cachedTables[db] = sorted(tables) if tables else tables

        return kb.data.cachedTables

    def searchTable(self):
        foundTbls = {}
        tblList = conf.tbl.split(',')
        rootQuery = queries[DBMS.MSSQL].search_table
        tblCond = rootQuery.inband.condition
        tblConsider, tblCondParam = self.likeOrExact("table")

        if conf.db == CURRENT_DB:
            conf.db = self.getCurrentDb()

        if conf.db:
            enumDbs = conf.db.split(',')
        elif not len(kb.data.cachedDbs):
            enumDbs = self.getDbs()
        else:
            enumDbs = kb.data.cachedDbs

        for db in enumDbs:
            db = safeSQLIdentificatorNaming(db)
            foundTbls[db] = []

        for tbl in tblList:
            tbl = safeSQLIdentificatorNaming(tbl, True)

            infoMsg = u"搜索表"
            if tblConsider == "1":
                infoMsg += "s LIKE"
            infoMsg += " '%s'" % unsafeSQLIdentificatorNaming(tbl)
            logger.info(infoMsg)

            tblQuery = "%s%s" % (tblCond, tblCondParam)
            tblQuery = tblQuery % unsafeSQLIdentificatorNaming(tbl)

            for db in foundTbls.keys():
                db = safeSQLIdentificatorNaming(db)

                if conf.excludeSysDbs and db in self.excludeDbsList:
                    infoMsg = u"跳过系统数据库'%s'" % db
                    logger.info(infoMsg)

                    continue

                if any(isTechniqueAvailable(_) for _ in (PAYLOAD.TECHNIQUE.UNION, PAYLOAD.TECHNIQUE.ERROR, PAYLOAD.TECHNIQUE.QUERY)) or conf.direct:
                    query = rootQuery.inband.query.replace("%s", db)
                    query += tblQuery
                    values = inject.getValue(query, blind=False, time=False)

                    if not isNoneValue(values):
                        if isinstance(values, basestring):
                            values = [values]

                        for foundTbl in values:
                            if foundTbl is None:
                                continue

                            foundTbls[db].append(foundTbl)
                else:
                    infoMsg = "fetching number of table"
                    if tblConsider == "1":
                        infoMsg += "s LIKE"
                    infoMsg += " '%s' in database '%s'" % (unsafeSQLIdentificatorNaming(tbl), unsafeSQLIdentificatorNaming(db))
                    logger.info(infoMsg)

                    query = rootQuery.blind.count
                    query = query.replace("%s", db)
                    query += " AND %s" % tblQuery
                    count = inject.getValue(query, union=False, error=False, expected=EXPECTED.INT, charsetType=CHARSET_TYPE.DIGITS)

                    if not isNumPosStrValue(count):
                        warnMsg = "no table"
                        if tblConsider == "1":
                            warnMsg += "s LIKE"
                        warnMsg += " '%s' " % unsafeSQLIdentificatorNaming(tbl)
                        warnMsg += "in database '%s'" % unsafeSQLIdentificatorNaming(db)
                        logger.warn(warnMsg)

                        continue

                    indexRange = getLimitRange(count)

                    for index in indexRange:
                        query = rootQuery.blind.query
                        query = query.replace("%s", db)
                        query += " AND %s" % tblQuery
                        query = agent.limitQuery(index, query, tblCond)
                        tbl = inject.getValue(query, union=False, error=False)
                        kb.hintValue = tbl
                        foundTbls[db].append(tbl)

        for db, tbls in foundTbls.items():
            if len(tbls) == 0:
                foundTbls.pop(db)

        if not foundTbls:
            warnMsg = u"数据库中不存在你要找的表"
            logger.warn(warnMsg)
            return

        conf.dumper.dbTables(foundTbls)
        self.dumpFoundTables(foundTbls)

    def searchColumn(self):
        rootQuery = queries[DBMS.MSSQL].search_column
        foundCols = {}
        dbs = {}
        whereTblsQuery = ""
        infoMsgTbl = ""
        infoMsgDb = ""
        colList = conf.col.split(',')

        if conf.excludeCol:
            colList = [_ for _ in colList if _ not in conf.excludeCol.split(',')]

        origTbl = conf.tbl
        origDb = conf.db
        colCond = rootQuery.inband.condition
        tblCond = rootQuery.inband.condition2
        colConsider, colCondParam = self.likeOrExact("column")

        if conf.db == CURRENT_DB:
            conf.db = self.getCurrentDb()

        if conf.db:
            enumDbs = conf.db.split(',')
        elif not len(kb.data.cachedDbs):
            enumDbs = self.getDbs()
        else:
            enumDbs = kb.data.cachedDbs

        for db in enumDbs:
            db = safeSQLIdentificatorNaming(db)
            dbs[db] = {}

        for column in colList:
            column = safeSQLIdentificatorNaming(column)
            conf.db = origDb
            conf.tbl = origTbl

            infoMsg = "搜索列"
            if colConsider == "1":
                infoMsg += "s LIKE"
            infoMsg += " '%s'" % unsafeSQLIdentificatorNaming(column)

            foundCols[column] = {}

            if conf.tbl:
                _ = conf.tbl.split(',')
                whereTblsQuery = " AND (" + " OR ".join("%s = '%s'" % (tblCond, unsafeSQLIdentificatorNaming(tbl)) for tbl in _) + ")"
                infoMsgTbl = " for table%s '%s'" % ("s" if len(_) > 1 else "", ", ".join(tbl for tbl in _))

            if conf.db == CURRENT_DB:
                conf.db = self.getCurrentDb()

            if conf.db:
                _ = conf.db.split(',')
                infoMsgDb = " in database%s '%s'" % ("s" if len(_) > 1 else "", ", ".join(db for db in _))
            elif conf.excludeSysDbs:
                msg = "skipping system database%s '%s'" % ("s" if len(self.excludeDbsList) > 1 else "", ", ".join(db for db in self.excludeDbsList))
                logger.info(msg)
            else:
                infoMsgDb = u"跨所有数据库"

            logger.info("%s%s%s" % (infoMsg, infoMsgTbl, infoMsgDb))

            colQuery = "%s%s" % (colCond, colCondParam)
            colQuery = colQuery % unsafeSQLIdentificatorNaming(column)

            for db in filter(None, dbs.keys()):
                db = safeSQLIdentificatorNaming(db)

                if conf.excludeSysDbs and db in self.excludeDbsList:
                    continue

                if any(isTechniqueAvailable(_) for _ in (PAYLOAD.TECHNIQUE.UNION, PAYLOAD.TECHNIQUE.ERROR, PAYLOAD.TECHNIQUE.QUERY)) or conf.direct:
                    query = rootQuery.inband.query % (db, db, db, db, db, db)
                    query += " AND %s" % colQuery.replace("[DB]", db)
                    query += whereTblsQuery.replace("[DB]", db)
                    values = inject.getValue(query, blind=False, time=False)

                    if not isNoneValue(values):
                        if isinstance(values, basestring):
                            values = [values]

                        for foundTbl in values:
                            foundTbl = safeSQLIdentificatorNaming(unArrayizeValue(foundTbl), True)

                            if foundTbl is None:
                                continue

                            if foundTbl not in dbs[db]:
                                dbs[db][foundTbl] = {}

                            if colConsider == "1":
                                conf.db = db
                                conf.tbl = foundTbl
                                conf.col = column

                                self.getColumns(onlyColNames=True, colTuple=(colConsider, colCondParam), bruteForce=False)

                                if db in kb.data.cachedColumns and foundTbl in kb.data.cachedColumns[db]\
                                  and not isNoneValue(kb.data.cachedColumns[db][foundTbl]):
                                    dbs[db][foundTbl].update(kb.data.cachedColumns[db][foundTbl])
                                kb.data.cachedColumns = {}
                            else:
                                dbs[db][foundTbl][column] = None

                            if db in foundCols[column]:
                                foundCols[column][db].append(foundTbl)
                            else:
                                foundCols[column][db] = [foundTbl]
                else:
                    foundCols[column][db] = []

                    infoMsg = "fetching number of tables containing column"
                    if colConsider == "1":
                        infoMsg += "s LIKE"
                    infoMsg += " '%s' in database '%s'" % (column, db)
                    logger.info("%s%s" % (infoMsg, infoMsgTbl))

                    query = rootQuery.blind.count
                    query = query % (db, db, db, db, db, db)
                    query += " AND %s" % colQuery.replace("[DB]", db)
                    query += whereTblsQuery.replace("[DB]", db)
                    count = inject.getValue(query, union=False, error=False, expected=EXPECTED.INT, charsetType=CHARSET_TYPE.DIGITS)

                    if not isNumPosStrValue(count):
                        warnMsg = "no tables contain column"
                        if colConsider == "1":
                            warnMsg += "s LIKE"
                        warnMsg += " '%s' " % column
                        warnMsg += "in database '%s'" % db
                        logger.warn(warnMsg)

                        continue

                    indexRange = getLimitRange(count)

                    for index in indexRange:
                        query = rootQuery.blind.query
                        query = query % (db, db, db, db, db, db)
                        query += " AND %s" % colQuery.replace("[DB]", db)
                        query += whereTblsQuery.replace("[DB]", db)
                        query = agent.limitQuery(index, query, colCond.replace("[DB]", db))
                        tbl = inject.getValue(query, union=False, error=False)
                        kb.hintValue = tbl

                        tbl = safeSQLIdentificatorNaming(tbl, True)

                        if tbl not in dbs[db]:
                            dbs[db][tbl] = {}

                        if colConsider == "1":
                            conf.db = db
                            conf.tbl = tbl
                            conf.col = column

                            self.getColumns(onlyColNames=True, colTuple=(colConsider, colCondParam), bruteForce=False)

                            if db in kb.data.cachedColumns and tbl in kb.data.cachedColumns[db]:
                                dbs[db][tbl].update(kb.data.cachedColumns[db][tbl])
                            kb.data.cachedColumns = {}
                        else:
                            dbs[db][tbl][column] = None

                        foundCols[column][db].append(tbl)

        conf.dumper.dbColumns(foundCols, colConsider, dbs)
        self.dumpFoundColumn(dbs, foundCols, colConsider)