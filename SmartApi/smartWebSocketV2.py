import json
import logging
import ssl
import struct
import time

import websocket


class SmartWebSocketV2(object):
    """
    SmartAPI Web Socket version 2
    """

    ROOT_URI = "wss://smartapisocket.angelone.in/smart-stream"
    HEART_BEAT_MESSAGE = "ping"
    HEART_BEAT_INTERVAL = 10  # Adjusted to 10s
    LITTLE_ENDIAN_BYTE_ORDER = "<"
    RESUBSCRIBE_FLAG = False
    # HB_THREAD_FLAG = True

    # Available Actions
    SUBSCRIBE_ACTION = 1
    UNSUBSCRIBE_ACTION = 0

    # Possible Subscription Mode
    LTP_MODE = 1
    QUOTE = 2
    SNAP_QUOTE = 3
    DEPTH = 4

    # Exchange Type
    NSE_CM = 1
    NSE_FO = 2
    BSE_CM = 3
    BSE_FO = 4
    MCX_FO = 5
    NCX_FO = 7
    CDE_FO = 13

    # Subscription Mode Map
    SUBSCRIPTION_MODE_MAP = {
        1: "LTP",
        2: "QUOTE",
        3: "SNAP_QUOTE",
        4: "DEPTH"
    }

    wsapp = None
    input_request_dict = {}
    current_retry_attempt = 0

    def __init__(self, auth_token, api_key, client_code, feed_token, max_retry_attempt=1):
        """
            Initialise the SmartWebSocketV2 instance
            Parameters
            ------
            auth_token: string
                jwt auth token received from Login API
            api_key: string
                api key from Smart API account
            client_code: string
                angel one account id
            feed_token: string
                feed token received from Login API
        """
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_code = client_code
        self.feed_token = feed_token
        self.DISCONNECT_FLAG = True
        self.last_pong_timestamp = None
        self.MAX_RETRY_ATTEMPT = max_retry_attempt

        if not self._sanity_check():
            raise Exception("Provide valid value for all the tokens")

    def _sanity_check(self):
        return True
        # if self.auth_token is None or self.api_key is None or self.client_code is None or self.feed_token is None:
        #     return False
        # return True

    def _on_data(self, wsapp, data, data_type, continue_flag):

        if data_type == 2:
            parsed_message = self._parse_binary_data(data)
            self.on_data(wsapp, parsed_message)
        # else:
        #     self.on_data(wsapp, data)

    def _on_open(self, wsapp):
        if self.RESUBSCRIBE_FLAG:
            try:
                self.resubscribe()
                self.RESUBSCRIBE_FLAG = False  # Add this line to prevent resubscription on subsequent reconnects
            except Exception as e:
                logging.exception("exception while resubscribing")
                self.on_error(wsapp, e)
        self.on_open(wsapp)

    def _on_pong(self, wsapp, data):
        if data == self.HEART_BEAT_MESSAGE:
            timestamp = time.time()
            formatted_timestamp = time.strftime("%d-%m-%y %H:%M:%S", time.localtime(timestamp))
            print(f"In on pong function ==> {data}, Timestamp: {formatted_timestamp}")
            self.last_pong_timestamp = timestamp
        # else:
        # Handle the received feed data here
        # self.on_data(wsapp, data)

    def _on_ping(self, wsapp, data):
        timestamp = time.time()
        formatted_timestamp = time.strftime("%d-%m-%y %H:%M:%S", time.localtime(timestamp))
        print(f"In on ping function ==> {data}, Timestamp: {formatted_timestamp}")
        self.last_ping_timestamp = timestamp

    def check_connection_status(self):
        current_time = time.time()
        if self.last_pong_timestamp is not None and current_time - self.last_pong_timestamp > 2 * self.HEART_BEAT_MESSAGE:
            # Stale connection detected, take appropriate action
            self.close_connection()
            self.connect()

    def subscribe(self, correlation_id, mode, token_list):
        """
            This Function subscribe the price data for the given token
            Parameters
            ------
            correlation_id: string
                A 10 character alphanumeric ID client may provide which will be returned by the server in error response
                to indicate which request generated error response.
                Clients can use this optional ID for tracking purposes between request and corresponding error response.
            mode: integer
                It denotes the subscription type
                possible values -> 1, 2 and 3
                1 -> LTP
                2 -> Quote
                3 -> Snap Quote
            token_list: list of dict
                Sample Value ->
                    [
                        { "exchangeType": 1, "tokens": ["10626", "5290"]},
                        {"exchangeType": 5, "tokens": [ "234230", "234235", "234219"]}
                    ]
                    exchangeType: integer
                    possible values ->
                        1 -> nse_cm
                        2 -> nse_fo
                        3 -> bse_cm
                        4 -> bse_fo
                        5 -> mcx_fo
                        7 -> ncx_fo
                        13 -> cde_fo
                    tokens: list of string
        """
        try:
            request_data = {
                "correlationID": correlation_id,
                "action": self.SUBSCRIBE_ACTION,
                "params": {
                    "mode": mode,
                    "tokenList": token_list
                }
            }
            if mode == 4:
                for token in token_list:
                    if token.get('exchangeType') != 1:
                        raise ValueError("Invalid ExchangeType: Please check the exchange type and try again")

            if self.input_request_dict.get(mode, None) is None:
                self.input_request_dict[mode] = {}

            for token in token_list:
                if token['exchangeType'] in self.input_request_dict[mode]:
                    self.input_request_dict[mode][token['exchangeType']].extend(token["tokens"])
                else:
                    self.input_request_dict[mode][token['exchangeType']] = token["tokens"]

            if mode == self.DEPTH:
                total_tokens = sum(len(token["tokens"]) for token in token_list)
                quota_limit = 50
                if total_tokens > quota_limit:
                    raise Exception("Quota exceeded: You can subscribe to a maximum of {} tokens.".format(quota_limit))

            self.wsapp.send(json.dumps(request_data))
            self.RESUBSCRIBE_FLAG = True

        except Exception as e:
            print("Error:", e)
            raise e

    def unsubscribe(self, correlation_id, mode, token_list):
        """
            This function unsubscribe the data for given token
            Parameters
            ------
            correlation_id: string
                A 10 character alphanumeric ID client may provide which will be returned by the server in error response
                to indicate which request generated error response.
                Clients can use this optional ID for tracking purposes between request and corresponding error response.
            mode: integer
                It denotes the subscription type
                possible values -> 1, 2 and 3
                1 -> LTP
                2 -> Quote
                3 -> Snap Quote
            token_list: list of dict
                Sample Value ->
                    [
                        { "exchangeType": 1, "tokens": ["10626", "5290"]},
                        {"exchangeType": 5, "tokens": [ "234230", "234235", "234219"]}
                    ]
                    exchangeType: integer
                    possible values ->
                        1 -> nse_cm
                        2 -> nse_fo
                        3 -> bse_cm
                        4 -> bse_fo
                        5 -> mcx_fo
                        7 -> ncx_fo
                        13 -> cde_fo
                    tokens: list of string
        """
        try:
            request_data = {
                "correlationID": correlation_id,
                "action": self.UNSUBSCRIBE_ACTION,
                "params": {
                    "mode": mode,
                    "tokenList": token_list
                }
            }

            self.input_request_dict.update(request_data)
            self.wsapp.send(json.dumps(request_data))
            self.RESUBSCRIBE_FLAG = True
        except Exception as e:
            raise e

    def resubscribe(self):
        try:
            for key, val in self.input_request_dict.items():
                token_list = []
                for key1, val1 in val.items():
                    temp_data = {
                        'exchangeType': key1,
                        'tokens': val1
                    }
                    token_list.append(temp_data)
                request_data = {
                    "action": self.SUBSCRIBE_ACTION,
                    "params": {
                        "mode": key,
                        "tokenList": token_list
                    }
                }
                self.wsapp.send(json.dumps(request_data))
        except Exception as e:
            raise e

    def connect(self):
        """
            Make the web socket connection with the server
        """
        headers = {
            "Authorization": self.auth_token,
            "x-api-key": self.api_key,
            "x-client-code": self.client_code,
            "x-feed-token": self.feed_token
        }

        try:
            self.wsapp = websocket.WebSocketApp(self.ROOT_URI, header=headers, on_open=self._on_open,
                                                on_error=self._on_error, on_close=self._on_close, on_data=self._on_data,
                                                on_ping=self._on_ping,
                                                on_pong=self._on_pong)
            self.wsapp.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}, ping_interval=self.HEART_BEAT_INTERVAL,
                                   ping_payload=self.HEART_BEAT_MESSAGE)
        except Exception as e:
            raise e

    def close_connection(self):
        """
        Closes the connection
        """
        # self.RESUBSCRIBE_FLAG = False
        self.DISCONNECT_FLAG = True
        # self.HB_THREAD_FLAG = False
        if self.wsapp:
            self.wsapp.close()

    def _on_error(self, wsapp, error):
        # self.HB_THREAD_FLAG = False
        self.on_error(wsapp, error)
        self.RESUBSCRIBE_FLAG = True
        if self.current_retry_attempt < self.MAX_RETRY_ATTEMPT:
            self.current_retry_attempt += 1
            sleep_seconds = self.current_retry_attempt * 10
            logging.info("Attempting to resubscribe/reconnect... sleeping for %d ", sleep_seconds)
            time.sleep(sleep_seconds)
            logging.info("coming back from sleep")
            try:
                self.close_connection()
                self.connect()
            except Exception as e:
                logging.exception("Error occurred during resubscribe/reconnect")

        else:
            self.close_connection()

    def _on_close(self, wsapp, close_status_code, close_msg):
        # self.HB_THREAD_FLAG = False
        # print(self.wsapp.close_frame)
        self.on_close(wsapp,close_status_code,close_msg)

    def _parse_binary_data(self, binary_data):
        parsed_data = {
            "subscription_mode": self._unpack_data(binary_data, 0, 1, byte_format="B")[0],
            "exchange_type": self._unpack_data(binary_data, 1, 2, byte_format="B")[0],
            "token": SmartWebSocketV2._parse_token_value(binary_data[2:27]),
            "sequence_number": self._unpack_data(binary_data, 27, 35, byte_format="q")[0],
            "exchange_timestamp": self._unpack_data(binary_data, 35, 43, byte_format="q")[0],
            "last_traded_price": self._unpack_data(binary_data, 43, 51, byte_format="q")[0]
        }
        try:
            parsed_data["subscription_mode_val"] = self.SUBSCRIPTION_MODE_MAP.get(parsed_data["subscription_mode"])

            if parsed_data["subscription_mode"] in [self.QUOTE, self.SNAP_QUOTE]:
                parsed_data["last_traded_quantity"] = self._unpack_data(binary_data, 51, 59, byte_format="q")[0]
                parsed_data["average_traded_price"] = self._unpack_data(binary_data, 59, 67, byte_format="q")[0]
                parsed_data["volume_trade_for_the_day"] = self._unpack_data(binary_data, 67, 75, byte_format="q")[0]
                parsed_data["total_buy_quantity"] = self._unpack_data(binary_data, 75, 83, byte_format="d")[0]
                parsed_data["total_sell_quantity"] = self._unpack_data(binary_data, 83, 91, byte_format="d")[0]
                parsed_data["open_price_of_the_day"] = self._unpack_data(binary_data, 91, 99, byte_format="q")[0]
                parsed_data["high_price_of_the_day"] = self._unpack_data(binary_data, 99, 107, byte_format="q")[0]
                parsed_data["low_price_of_the_day"] = self._unpack_data(binary_data, 107, 115, byte_format="q")[0]
                parsed_data["closed_price"] = self._unpack_data(binary_data, 115, 123, byte_format="q")[0]

            if parsed_data["subscription_mode"] == self.SNAP_QUOTE:
                parsed_data["last_traded_timestamp"] = self._unpack_data(binary_data, 123, 131, byte_format="q")[0]
                parsed_data["open_interest"] = self._unpack_data(binary_data, 131, 139, byte_format="q")[0]
                parsed_data["open_interest_change_percentage"] = \
                    self._unpack_data(binary_data, 139, 147, byte_format="q")[0]
                parsed_data["upper_circuit_limit"] = self._unpack_data(binary_data, 347, 355, byte_format="q")[0]
                parsed_data["lower_circuit_limit"] = self._unpack_data(binary_data, 355, 363, byte_format="q")[0]
                parsed_data["52_week_high_price"] = self._unpack_data(binary_data, 363, 371, byte_format="q")[0]
                parsed_data["52_week_low_price"] = self._unpack_data(binary_data, 371, 379, byte_format="q")[0]
                best_5_buy_and_sell_data = self._parse_best_5_buy_and_sell_data(binary_data[147:347])
                parsed_data["best_5_buy_data"] = best_5_buy_and_sell_data["best_5_sell_data"]
                parsed_data["best_5_sell_data"] = best_5_buy_and_sell_data["best_5_buy_data"]

            if parsed_data["subscription_mode"] == self.DEPTH:
                parsed_data.pop("sequence_number", None)
                parsed_data.pop("last_traded_price", None)
                parsed_data.pop("subscription_mode_val", None)
                parsed_data["packet_received_time"] = self._unpack_data(binary_data, 35, 43, byte_format="q")[0]
                depth_data_start_index = 43
                depth_20_data = self._parse_depth_20_buy_and_sell_data(binary_data[depth_data_start_index:])
                parsed_data["depth_20_buy_data"] = depth_20_data["depth_20_buy_data"]
                parsed_data["depth_20_sell_data"] = depth_20_data["depth_20_sell_data"]

            return parsed_data
        except Exception as e:
            raise e

    def _unpack_data(self, binary_data, start, end, byte_format="I"):
        """
            Unpack Binary Data to the integer according to the specified byte_format.
            This function returns the tuple
        """
        return struct.unpack(self.LITTLE_ENDIAN_BYTE_ORDER + byte_format, binary_data[start:end])

    @staticmethod
    def _parse_token_value(binary_packet):
        token = ""
        for i in range(len(binary_packet)):
            if chr(binary_packet[i]) == '\x00':
                return token
            token += chr(binary_packet[i])
        return token

    def _parse_best_5_buy_and_sell_data(self, binary_data):

        def split_packets(binary_packets):
            packets = []

            i = 0
            while i < len(binary_packets):
                packets.append(binary_packets[i: i + 20])
                i += 20
            return packets

        best_5_buy_sell_packets = split_packets(binary_data)

        best_5_buy_data = []
        best_5_sell_data = []

        for packet in best_5_buy_sell_packets:
            each_data = {
                "flag": self._unpack_data(packet, 0, 2, byte_format="H")[0],
                "quantity": self._unpack_data(packet, 2, 10, byte_format="q")[0],
                "price": self._unpack_data(packet, 10, 18, byte_format="q")[0],
                "no of orders": self._unpack_data(packet, 18, 20, byte_format="H")[0]
            }

            if each_data["flag"] == 0:
                best_5_buy_data.append(each_data)
            else:
                best_5_sell_data.append(each_data)

        return {
            "best_5_buy_data": best_5_buy_data,
            "best_5_sell_data": best_5_sell_data
        }

    def _parse_depth_20_buy_and_sell_data(self, binary_data):
        depth_20_buy_data = []
        depth_20_sell_data = []

        for i in range(20):
            buy_start_idx = i * 10
            sell_start_idx = 200 + i * 10

            # Parse buy data
            buy_packet_data = {
                "quantity": self._unpack_data(binary_data, buy_start_idx, buy_start_idx + 4, byte_format="i")[0],
                "price": self._unpack_data(binary_data, buy_start_idx + 4, buy_start_idx + 8, byte_format="i")[0],
                "num_of_orders": self._unpack_data(binary_data, buy_start_idx + 8, buy_start_idx + 10, byte_format="h")[
                    0],
            }

            # Parse sell data
            sell_packet_data = {
                "quantity": self._unpack_data(binary_data, sell_start_idx, sell_start_idx + 4, byte_format="i")[0],
                "price": self._unpack_data(binary_data, sell_start_idx + 4, sell_start_idx + 8, byte_format="i")[0],
                "num_of_orders":
                    self._unpack_data(binary_data, sell_start_idx + 8, sell_start_idx + 10, byte_format="h")[0],
            }

            depth_20_buy_data.append(buy_packet_data)
            depth_20_sell_data.append(sell_packet_data)

        return {
            "depth_20_buy_data": depth_20_buy_data,
            "depth_20_sell_data": depth_20_sell_data
        }

    # def on_message(self, wsapp, message):
    #     print(message)

    def on_data(self, wsapp, data):
        pass

    def on_close(self, wsapp,close_status_code,close_msg):
        pass

    def on_open(self, wsapp):
        pass

    def on_error(self, wsapp, error):
        pass
