import pytest
from unittest.mock import Mock

from margin_trading.account_manager import MarginAccountManager, MarginAccountInfo, MarginPosition


class TestMarginAccountManager:
    """Test MarginAccountManager functionality"""

    @pytest.fixture
    def mock_client(self):
        """Create mock Binance client"""
        client = Mock()
        client.get_margin_account.return_value = {
            'tradeEnabled': True,
            'transferEnabled': True,
            'borrowEnabled': True,
            'totalAssetOfBtc': '1.5',
            'totalLiabilityOfBtc': '0.5',
            'totalNetAssetOfBtc': '1.0',
            'userAssets': [
                {'asset': 'BTC', 'free': '0.5', 'borrowed': '0.0', 'netAsset': '0.5'},
                {'asset': 'USDT', 'free': '10000', 'borrowed': '5000', 'netAsset': '5000'},
            ]
        }
        client.get_symbol_ticker.return_value = {'price': '50000.0'}
        return client

    def test_initialization_without_client(self):
        """Test that initialization fails without client"""
        with pytest.raises(ValueError, match="binance_client is required"):
            MarginAccountManager(binance_client=None)

    def test_get_account_info(self, mock_client):
        """Test fetching account info"""
        manager = MarginAccountManager(binance_client=mock_client)
        info = manager.get_account_info()

        assert isinstance(info, MarginAccountInfo)
        assert info.total_asset_btc == 1.5
        assert info.total_liability_btc == 0.5
        assert info.net_asset_btc == 1.0
        assert info.leverage_ratio > 0

    def test_get_available_margin(self, mock_client):
        """Test calculating available margin"""
        manager = MarginAccountManager(binance_client=mock_client)
        margin = manager.get_available_margin('USDT')

        assert margin > 0
        mock_client.get_margin_account.assert_called()

    def test_get_position_details(self, mock_client):
        """Test getting position details for a symbol"""
        manager = MarginAccountManager(binance_client=mock_client)
        position = manager.get_position_details('BTCUSDT')

        assert isinstance(position, MarginPosition)
        assert position.symbol == 'BTCUSDT'
        assert position.base_asset == 'BTC'
        assert position.quote_asset == 'USDT'
        assert position.net_position > 0

    def test_calculate_liquidation_risk_low(self, mock_client):
        """Test liquidation risk with safe margin level"""
        mock_client.get_margin_account.return_value = {
            'totalAssetOfBtc': '2.0',
            'totalLiabilityOfBtc': '0.5',
            'totalNetAssetOfBtc': '1.5',
            'userAssets': [],
            'tradeEnabled': True,
        }
        manager = MarginAccountManager(binance_client=mock_client)
        risk = manager.calculate_liquidation_risk()

        assert risk['is_at_risk'] is False
        assert risk['risk_level'] == 'low'

    def test_calculate_liquidation_risk_high(self, mock_client):
        """Test liquidation risk with dangerous margin level"""
        mock_client.get_margin_account.return_value = {
            'totalAssetOfBtc': '1.1',
            'totalLiabilityOfBtc': '1.0',
            'totalNetAssetOfBtc': '0.1',
            'userAssets': [],
            'tradeEnabled': True,
        }
        manager = MarginAccountManager(binance_client=mock_client)
        risk = manager.calculate_liquidation_risk()

        assert risk['is_at_risk'] is True
        assert risk['risk_level'] in ['high', 'critical']
