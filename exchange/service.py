from .audit import history
from .availability import Availability
from .catalog import Catalog
from .db import connect
from .delivery import Delivery
from .grants import Grants
from .handovers import Handovers
from .policy import Policies
from .products import Products
from .tenure import Tenures


class Exchange:
    def __init__(self, database):
        self.connection = connect(database)
        self.catalog = Catalog(self.connection)
        self.grants = Grants(self.connection)
        self.policies = Policies(self.connection)
        self.products = Products(self.connection)
        self.delivery = Delivery(self.connection)
        self.tenures = Tenures(self.connection)
        self.handovers = Handovers(self.connection)
        self.availability = Availability(self.connection)

    def history(self, subject):
        return history(self.connection, subject)

    def close(self):
        self.connection.close()
