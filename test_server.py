import unittest
import os
import queue
from starlette.applications import Starlette
from starlette.routing import Route
from unittest.mock import patch
import pandas as pd
from starlette.testclient import TestClient
import server


class ServiceTests(unittest.TestCase):
    def test_telegram_ticker_parser(self):
        self.assertEqual(server.parse_telegram('COMPARE Microsoft $NVDA'),'MSFT,NVDA')
        self.assertEqual(server.parse_telegram('/compare@mybot AAPL, MSFT AAPL'),'AAPL,MSFT')
        for text in ('https://evil.test','A B C D E F',''):
            with self.assertRaises(ValueError): server.parse_telegram(text)

    def test_telegram_webhook_auth_dedup_and_throttle(self):
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'fake-test-token','TELEGRAM_ALLOWED_CHAT_IDS':''}), \
             patch.object(server,'telegram_queue',queue.Queue(maxsize=4)), \
             patch.object(server,'telegram_seen',{}),patch.object(server,'telegram_last',{}):
            app=Starlette(routes=[Route('/telegram/webhook',server.telegram_webhook,methods=['POST'])])
            with TestClient(app,base_url='http://localhost') as client:
                data={'update_id':1,'message':{'chat':{'id':99,'type':'private'},'text':'MSFT NVDA'}}
                self.assertEqual(client.post('/telegram/webhook',json=data).status_code,403)
                h={'X-Telegram-Bot-Api-Secret-Token':server.telegram_secret()}
                r=client.post('/telegram/webhook',headers=h,json=data)
                self.assertIn('Retrieving',r.json()['text'])
                self.assertEqual(server.telegram_queue.qsize(),1)
                client.post('/telegram/webhook',headers=h,json=data)
                self.assertEqual(server.telegram_queue.qsize(),1)
                data['update_id']=2
                r=client.post('/telegram/webhook',headers=h,json=data)
                self.assertIn('wait one minute',r.json()['text'])
                self.assertEqual(server.telegram_queue.qsize(),1)

    def test_telegram_reply_uploads_generated_chart(self):
        result={'as_of':'2026-11-06','basis':'Adjusted','metadata':{'MSFT':{'currency':'USD'}},
                'performance':{'1D':{'MSFT':{'return_pct':1.25}}},'correlations':{'3Y':{}},
                'charts':[{'title':'price','url':'https://example.test/charts/test/price.png'}]}
        with patch.object(server,'get_stock_history',return_value=result), \
             patch.object(server,'charts',{'test':(0,{'price':b'fake-png'})}), \
             patch.object(server,'telegram_api') as api:
            server.telegram_process(99,'MSFT')
        self.assertEqual(api.call_args_list[0].args[0],'sendMessage')
        self.assertIn('+1.25%',api.call_args_list[0].args[1]['text'])
        self.assertEqual(api.call_args_list[1].args[0],'sendPhoto')
        self.assertEqual(api.call_args_list[1].args[2]['photo'][1],b'fake-png')

    def test_daily_metrics_and_short_window_correlation(self):
        dates=pd.bdate_range('2022-01-03','2026-11-06')
        import numpy as np
        a=pd.Series(100*np.exp(np.cumsum(.001+.005*np.sin(np.arange(len(dates))))),index=dates)
        prices=pd.DataFrame({'AAA':a,'BBB':a*2})
        frames={s:pd.DataFrame({'close':prices[s],'high':prices[s]*1.01,'low':prices[s]*.99,'volume':100},index=dates) for s in prices}
        metrics,corr,_,anchor=server.calculate(prices,frames)
        self.assertAlmostEqual(corr['3Y']['AAA/BBB']['r'],1)
        self.assertIsNone(corr['1W']['AAA/BBB']['r'])
        self.assertEqual(corr['1W']['AAA/BBB']['n'],5)
        self.assertAlmostEqual(metrics['1D']['AAA']['return_pct'],(a.iloc[-1]/a.iloc[-2]-1)*100,places=3)

    def test_short_history_does_not_claim_three_year_metrics(self):
        idx=pd.bdate_range('2026-01-01','2026-11-06')
        prices=pd.DataFrame({'AAA':range(100,100+len(idx)), 'BBB':range(200,200+len(idx))},index=idx)
        frames={s:pd.DataFrame({'close':prices[s],'high':prices[s],'low':prices[s],'volume':100},index=idx) for s in prices}
        metrics,corr,_,_=server.calculate(prices,frames)
        self.assertIsNone(metrics['3Y']['AAA']['return_pct'])
        self.assertIsNone(corr['3Y']['AAA/BBB']['r'])

    def test_validation(self):
        for args in [('https://evil','2026-01-01','2026-02-01','1d'),
                     ('MSFT','2026-02-01','2026-01-01','1d'),
                     ('MSFT','2020-01-01','2026-01-01','1d'),
                     ('MSFT','2026-01-01','2026-02-01','1m')]:
            with self.assertRaises(ValueError):
                server.validate(*args)

    def test_csv_preserves_exchange_daily_dates_and_missing_values(self):
        frame = pd.DataFrame({'Close':[100.,101.,-1.], 'Adj Close':[99.,None,0.],
                              'Volume':[10,20,0]},
                             index=pd.date_range('2026-01-01',periods=3,tz='Asia/Tokyo'))
        csv = server.encode(frame,'1d')
        self.assertIn('2026-01-01,100,99,10',csv)
        self.assertIn('2026-01-02,101,,20',csv)
        self.assertNotIn('2026-01-03',csv)

    def test_failures_do_not_fabricate_prices(self):
        with patch.object(server,'fetch',side_effect=RuntimeError('internal private details')):
            result=server.get_stock_history('MSFT','2026-01-01','2026-02-01')
        self.assertIsNone(result['csv'])
        self.assertNotIn('private details',result['message'])

    def test_mcp_protocol_lists_and_calls_tool(self):
        with TestClient(server.mcp.streamable_http_app(),base_url='http://localhost') as client:
            self.assertEqual(client.get('/health').status_code,200)
            headers={'Accept':'application/json, text/event-stream'}
            def rpc(method,params):
                return client.post('/mcp',headers=headers,json={
                    'jsonrpc':'2.0','id':1,'method':method,'params':params})
            r=rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},
                               'clientInfo':{'name':'test','version':'1'}})
            self.assertEqual(r.status_code,200,r.text)
            r=rpc('tools/list',{})
            self.assertEqual(r.status_code,200,r.text)
            self.assertEqual(r.json()['result']['tools'][0]['name'],'get_stock_history')
            with patch.object(server,'fetch',return_value={'csv':'timestamp,close\n2026-01-01,100\n','observations':1}):
                r=rpc('tools/call',{'name':'get_stock_history','arguments':{
                    'symbol':'MSFT','start':'2026-01-01','end':'2026-02-01'}})
            self.assertEqual(r.status_code,200,r.text)
            self.assertIn('2026-01-01',r.text)


if __name__=='__main__':
    unittest.main()
