# -*- coding: utf-8 -*-

# from utility.enum import enum
from tornado.platform.asyncio import AsyncIOMainLoop
from crypto_trading.service.base import ServiceState, ServiceBase, start_service
import logging
import zmq.asyncio
import asyncio
import tornado
import json
import pickle
import time



QUOTE_GAP = 0.003
WITHIN_SECONDS = 32 * 24 * 3600		# 32 days

quotes = {}


class CatchGap(ServiceBase):
    
    def __init__(self, logger_name):
        ServiceBase.__init__(self, logger_name)

        # servie id used for control
        # self.sid = 'sid002'
        
        # SUB data
        self.deribitmsgclient = self.ctx.socket(zmq.SUB)
        self.deribitmsgclient.connect('tcp://localhost:9000')
        self.deribitmsgclient.setsockopt_string(zmq.SUBSCRIBE, '')

        self.okexmsgclient = self.ctx.socket(zmq.SUB)
        self.okexmsgclient.connect('tcp://localhost:9100')
        self.okexmsgclient.setsockopt_string(zmq.SUBSCRIBE, '')

    async def find_quotes_gap(self):
        for k, v in quotes.items():
            if all(( not v.get('gapped', False),
                     time.mktime(time.strptime(k.split('-')[1], '%d%b%y')) - time.time() < WITHIN_SECONDS,
                     v.get('delta', 1) <= 0.3,
                     # OTM & at least 1 sigma & CALL
            )):
                if 'deribit' in v.keys() and 'okex' in v.keys():
                    if v['deribit'][0] and v['okex'][2]:
                        if v['deribit'][0] - float(v['okex'][2]) >= QUOTE_GAP:
                            self.logger.info('%s -- gap: %.4f -- %s' %(k, v['deribit'][0] - float(v['okex'][2]), str(v)))
                            v['gapped'] = True
                            asyncio.ensure_future(self.gap_transaction(k, v))
                    if v['deribit'][2] and v['okex'][0]:
                        if float(v['okex'][0]) - v['deribit'][2] >= QUOTE_GAP:
                            self.logger.info('%s -- gap: %.4f -- %s' %(k, float(v['okex'][0]) - v['deribit'][2], str(v)))
                            v['gapped'] = True
                            asyncio.ensure_future(self.gap_transaction(k, v))

    async def gap_transaction(self, sym, quotes):
        # 1. make sure both platforms can trade
        # 2. find out which side price is beyond the deribit mark price, trade it firstly; if almost even, long firstly, then short
        # 3. calculate how many contracts need to be traded concerning sizes and account situation
        # 4. trade at one platform and make sure that it returns successfully, if not, how to deal with it?
        # 5. trade at the other platform
        # 6. check everything alright
        pass

    async def sub_msg_deribit(self):
        while self.state == ServiceState.started:
            msg = json.loads(await self.deribitmsgclient.recv_string())
            if msg['type'] == 'quote':
                quote = pickle.loads(eval(msg['data']))
                # print(quote)
                newrecord = [quote['bid_prices'][0], quote['bid_sizes'][0], quote['ask_prices'][0], quote['ask_sizes'][0]]
                if quotes.setdefault(quote['sym'], {}).get('deribit', []) != newrecord:
                    quotes[quote['sym']].update({'deribit': newrecord, 'gapped': False,
                                                 'index_price': quote['index_price'], 'mark_price': quote['mark_price'],
                                                 'delta': quote['delta'], })
                    await self.find_quotes_gap()

    async def sub_msg_okex(self):
        while self.state == ServiceState.started:
            msg = json.loads(await self.okexmsgclient.recv_string())
            if msg['table'] == 'option/depth5':
                quote = msg['data'][0]
                # print(quote)
                tmp = quote['instrument_id'].split('-')
                sym = '-'.join([tmp[0], time.strftime('%d%b%y', time.strptime(tmp[2], '%y%m%d')).upper(),
                                tmp[3], tmp[4]])
                newrecord = [quote['bids'][0][0] if len(quote['bids']) > 0 else None,
                             quote['bids'][0][1] if len(quote['bids']) > 0 else None,
                             quote['asks'][0][0] if len(quote['asks']) > 0 else None,
                             quote['asks'][0][1] if len(quote['asks']) > 0 else None]
                if quotes.setdefault(sym, {}).get('okex', []) != newrecord:
                    quotes[sym]['okex'] = newrecord
                    quotes[sym]['gapped'] = False
                    await self.find_quotes_gap()
                
    async def run(self):
        if self.state == ServiceState.started:
            self.logger.error('tried to run service, but state is %s' % self.state)
        else:
            print('Here in run body')
            self.state = ServiceState.started
            # await self.sub_msg()
            asyncio.ensure_future(self.sub_msg_deribit())
            asyncio.ensure_future(self.sub_msg_okex())

    
if __name__ == '__main__':
    service = CatchGap('catch_gap')
    start_service(service, {})
