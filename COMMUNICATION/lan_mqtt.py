#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USI Smart Retail OS - LAN MQTT Communication Service
Edge PC communication bridge between Smart Shelf, Checkout, and Employee devices
Uses MQTT protocol over local network
"""

import json
import time
import sys
from pathlib import Path
from datetime import datetime

# ============================================
# NOTE: This defines the communication interface
# For production: pip install paho-mqtt
# Use docker-compose to start MQTT Broker
# ============================================

class SimulatedMQTTBroker:
    """Simulated MQTT Broker (dev/test only)"""
    
    def __init__(self, host='localhost', port=1883):
        self.host = host
        self.port = port
        self.messages = []
        self.subscribers = {}
        
    def publish(self, topic, message):
        msg = {
            'topic': topic,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }
        self.messages.append(msg)
        print(f"  [MQTT] Publish: {topic}")
        return msg
    
    def subscribe(self, topic, callback):
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(callback)
        print(f"  [MQTT] Subscribe: {topic}")
    
    def get_messages(self, topic=None):
        if topic:
            return [m for m in self.messages if m['topic'] == topic]
        return self.messages


class SmartShelfMQTTClient:
    """Smart Shelf MQTT Client"""
    
    TOPIC_PREFIX = 'usi/smartshelf'
    
    def __init__(self, store_id, shelf_id):
        self.store_id = store_id
        self.shelf_id = shelf_id
        self.broker = None
    
    def connect(self, broker):
        self.broker = broker
        print(f"[{self.store_id}/{self.shelf_id}] Connected to Broker")
    
    def publish_status(self, status_data):
        if not self.broker:
            return
        topic = f"{self.TOPIC_PREFIX}/{self.store_id}/{self.shelf_id}/status"
        self.broker.publish(topic, status_data)
    
    def publish_alert(self, alert_type, message):
        if not self.broker:
            return
        topic = f"{self.TOPIC_PREFIX}/{self.store_id}/{self.shelf_id}/alert"
        self.broker.publish(topic, {
            'type': alert_type,
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
    
    def subscribe_commands(self, callback):
        if not self.broker:
            return
        topic = f"{self.TOPIC_PREFIX}/{self.store_id}/{self.shelf_id}/command"
        self.broker.subscribe(topic, callback)


class CheckoutMQTTClient:
    """Checkout Terminal MQTT Client"""
    
    TOPIC_PREFIX = 'usi/checkout'
    
    def __init__(self, store_id, terminal_id):
        self.store_id = store_id
        self.terminal_id = terminal_id
        self.broker = None
    
    def connect(self, broker):
        self.broker = broker
        print(f"[{self.store_id}/{self.terminal_id}] Checkout terminal connected")
    
    def publish_transaction(self, transaction_data):
        if not self.broker:
            return
        topic = f"{self.TOPIC_PREFIX}/{self.store_id}/{self.terminal_id}/transaction"
        self.broker.publish(topic, transaction_data)
    
    def request_inventory_check(self, product_id):
        if not self.broker:
            return
        topic = f"{self.TOPIC_PREFIX}/{self.store_id}/inventory/request"
        self.broker.publish(topic, {
            'product_id': product_id,
            'timestamp': datetime.now().isoformat()
        })


class EdgeSyncService:
    """Edge Sync Service (LAN Core)"""
    
    def __init__(self, store_id):
        self.store_id = store_id
        self.broker = SimulatedMQTTBroker()
        self.smart_shelf_clients = {}
        self.checkout_clients = {}
        self.local_db = Path(f'EDGE/{store_id}/smartshelf/processed/shelf_history_tmp.db')
    
    def register_smart_shelf(self, shelf_id):
        client = SmartShelfMQTTClient(self.store_id, shelf_id)
        client.connect(self.broker)
        self.smart_shelf_clients[shelf_id] = client
        client.subscribe_commands(self._handle_shelf_command)
        return client
    
    def register_checkout(self, terminal_id):
        client = CheckoutMQTTClient(self.store_id, terminal_id)
        client.connect(self.broker)
        self.checkout_clients[terminal_id] = client
        return client
    
    def _handle_shelf_command(self, command_data):
        print(f"[SyncService] Received command: {command_data}")
    
    def sync_inventory(self):
        print(f"[SyncService] Syncing {self.store_id} inventory...")
        
        if not self.local_db.exists():
            print(f"  [WARN] DB not found: {self.local_db}")
            return
        
        import sqlite3
        conn = sqlite3.connect(str(self.local_db))
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT product_id, product_name, stock_quantity
            FROM enhanced_inventory
            ORDER BY product_name
        """)
        
        inventory = [dict(zip(['product_id','product_name','stock'], row)) 
                    for row in cursor.fetchall()]
        conn.close()
        
        print(f"  [OK] Synced {len(inventory)} products")
        return inventory
    
    def get_status(self):
        return {
            'store_id': self.store_id,
            'smart_shelves': len(self.smart_shelf_clients),
            'checkout_terminals': len(self.checkout_clients),
            'total_messages': len(self.broker.messages)
        }


def run_lan_communication_demo():
    """Run LAN communication demo"""
    print("="*60)
    print("USI Smart Retail OS - LAN Communication Demo")
    print("="*60)
    
    # Create Edge sync service
    edge = EdgeSyncService('store_001')
    
    # Register devices
    shelf = edge.register_smart_shelf('shelf_001')
    checkout = edge.register_checkout('terminal_001')
    
    print("\nDevice Connection Status:")
    print(f"  Smart Shelf: shelf_001 [OK]")
    print(f"  Checkout: terminal_001 [OK]")
    
    # Simulate data flow
    print("\nSimulating Data Flow:")
    print("-"*40)
    
    # 1. Shelf publishes status
    print("\n[1] Shelf publishing status...")
    shelf.publish_status({
        'slot_count': 10,
        'occupied': 7,
        'last_scan': datetime.now().isoformat()
    })
    
    # 2. Checkout requests inventory
    print("\n[2] Checkout requesting inventory check...")
    checkout.request_inventory_check('PROD10001')
    
    # 3. Edge sync
    print("\n[3] Edge syncing inventory...")
    inventory = edge.sync_inventory()
    
    # 4. Shelf publishes OOS alert
    print("\n[4] Shelf publishing OOS alert...")
    shelf.publish_alert('OOS', 'Slot 3 product out of stock')
    
    # 5. Checkout publishes transaction
    print("\n[5] Checkout publishing transaction...")
    checkout.publish_transaction({
        'transaction_id': f'TXN{int(time.time())}',
        'items': [
            {'product_id': 'PROD10001', 'quantity': 2, 'amount': 598.0}
        ],
        'total': 598.0,
        'timestamp': datetime.now().isoformat()
    })
    
    # Show communication log
    print("\nCommunication Log:")
    print("-"*40)
    for msg in edge.broker.messages:
        print(f"  [{msg['topic']}]")
        if isinstance(msg['message'], dict):
            for k, v in msg['message'].items():
                print(f"    {k}: {v}")
        print()
    
    print("-"*40)
    print("[OK] LAN communication demo complete")
    print(f"  Total messages: {len(edge.broker.messages)}")

if __name__ == '__main__':
    run_lan_communication_demo()
