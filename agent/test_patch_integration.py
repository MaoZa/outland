"""
测试 webrtc_manager.py 中的 monkey patch 是否正确生效
"""
import sys
import os

# 确保 agent 目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ifaddr

# 先 patch ifaddr（模拟 Docker 环境返回空）
_original = ifaddr.get_adapters
def mock_empty():
    print('[Mock] ifaddr.get_adapters() 返回空列表')
    return []
ifaddr.get_adapters = mock_empty

# 直接导入 webrtc_manager（会执行 patch）
print('[Step 1] 导入 services.webrtc_manager...')
import services.webrtc_manager as wm
print('[Step 1] 导入完成')

# 测试 patch 是否生效
print('[Step 2] 测试 get_host_addresses...')
import aioice.ice
addresses = aioice.ice.get_host_addresses(use_ipv4=True, use_ipv6=False)
print(f'[Step 2] 结果: {addresses}')

if '0.0.0.0' in addresses:
    print('[OK] Monkey patch 生效！')
else:
    print('[FAIL] Monkey patch 未生效')
