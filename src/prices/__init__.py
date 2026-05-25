from .assets import AssetPrices
from .options import OptionsPrices


class Prices:
    """Facade composing `self.asset` (stocks/crypto/forex) and `self.options`,
    both sharing one `data_dir`."""

    def __init__(self, data_dir: str) -> None:
        self.asset = AssetPrices(data_dir)
        self.options = OptionsPrices(self.asset)
