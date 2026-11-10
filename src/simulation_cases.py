TEST_CASES = [
    (
        "Counts the number of orders placed by each customer in the top 5",
        """| CustomerID | OrderCount |
        | --- | --- |
        | BSBEV | 210 |
        | RICAR | 203 |
        | LILAS | 203 |
        | GOURL | 202 |
        | PRINI | 200 |
        # |""",
            ),

            (
                "Compute the units sold for each of the top 5 products by aggregating the quantity values from the order details",
                """| ProductName | TotalUnitsSold |
        | --- | --- |
        | Louisiana Hot Spiced Okra | 206213 |
        | Sir Rodney's Marmalade | 205637 |
        | Teatime Chocolate Biscuits | 205487 |
        | Sirop d'érable | 205005 |
        | Gumbär Gummibärchen | 204761 |
        |""",
            ),

            (
                "Calculate the average unit price of products grouped by their category.",
                """| CategoryName | average_unit_price |
        | --- | --- |
        | Beverages | 37.979166666666664 |
        | Condiments | 23.0625 |
        | Confections | 25.16 |
        | Dairy Products | 28.73 |
        | Grains/Cereals | 20.25 |
        | Meat/Poultry | 54.00666666666667 |
        | Produce | 32.37 |
        | Seafood | 20.6825 |
        |""",
            ),

            (
                "Count how many orders each employee has processed",
                """| EmployeeID | OrderCount |
        | --- | --- |
        | 1 | 1846 |
        | 2 | 1771 |
        | 3 | 1846 |
        | 4 | 1908 |
        | 5 | 1804 |
        | 6 | 1754 |
        | 7 | 1789 |
        | 8 | 1798 |
        | 9 | 1766 |
        |""",
            ),

            (
                "List the five products with the highest unit price",
                """| ProductName | UnitPrice |
        | --- | --- |
        | Côte de Blaye | 263.5 |
        | Thüringer Rostbratwurst | 123.79 |
        | Mishi Kobe Niku | 97 |
        | Sir Rodney's Marmalade | 81 |
        | Carnarvon Tigers | 62.5 |
        |""",
            ),

            (
                "Counts how many sales were made with and without a discount",
                """| sales_with_discount | sales_without_discount |
        | --- | --- |
        | 838 | 608445 |
        |""",
            ),

            (
                "Calculate the total revenue generated from the product 'Chai'",
                """| total_revenue |
        | --- |
        | 3632174.1 |
        |""",
            ),

            (
                "Counts how many products each supplier provides",
                """| CompanyName | ProductCount |
        | --- | --- |
        | Aux joyeux ecclésiastiques | 2 |
        | Bigfoot Breweries | 3 |
        | Cooperativa de Quesos 'Las Cabras' | 2 |
        | Escargots Nouveaux | 1 |
        | Exotic Liquids | 3 |
        | Formaggi Fortini s.r.l. | 3 |
        | Forêts d'érables | 2 |
        | G'day, Mate | 3 |
        | Gai pâturage | 2 |
        | Grandma Kelly's Homestead | 3 |
        | Heli Süßwaren GmbH & Co. KG | 3 |
        | Karkki Oy | 3 |
        | Leka Trading | 3 |
        | Lyngbysild | 2 |
        | Ma Maison | 2 |
        | Mayumi's | 3 |
        | New England Seafood Cannery | 2 |
        | New Orleans Cajun Delights | 4 |
        | Nord-Ost-Fisch Handelsgesellschaft mbH | 1 |
        | Norske Meierier | 3 |
        | PB Knäckebröd AB | 2 |
        | Pasta Buttini s.r.l. | 2 |
        | Pavlova, Ltd. | 5 |
        | Plutzer Lebensmittelgroßmärkte AG | 5 |
        | Refrescos Americanas LTDA | 1 |
        | Specialty Biscuits, Ltd. | 4 |
        | Svensk Sjöföda AB | 3 |
        | Tokyo Traders | 3 |
        | Zaanse Snoepfabriek | 2 |
        |""",
            ),

            (
                "List employees and their manager",
                """| EmployeeName | ManagerName |
        | --- | --- |
        | Nancy Davolio | Andrew Fuller |
        | Andrew Fuller | |
        | Janet Leverling | Andrew Fuller |
        | Margaret Peacock | Andrew Fuller |
        | Steven Buchanan | Andrew Fuller |
        | Michael Suyama | Steven Buchanan |
        | Robert King | Steven Buchanan |
        | Laura Callahan | Andrew Fuller |
        | Anne Dodsworth | Steven Buchanan |
        |""",
            ),

            (
                "Lists the top 5 orders with the most expensive shipping fees",
                """| OrderID | Freight |
        | --- | --- |
        | 13460 | 587 |
        | 17596 | 580.75 |
        | 13372 | 574.5 |
        | 13466 | 568.25 |
        | 25679 | 561.25 |
        |""",
            ),
    ]
