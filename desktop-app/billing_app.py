def calculate_bill(items):
    prices = {'chips': 5, 'chocolates': 20, 'biscuits': 10}
    total = sum(prices[item] * count for item, count in items.items())
    return total

# Test run with example items
items = {'chips': 3, 'chocolates': 2, 'biscuits': 5}
total_bill = calculate_bill(items)
print(f'The total bill is {total_bill} rupees.')