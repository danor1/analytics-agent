"""
Database configuration and schema definitions.
"""

# TODO: convert to a pydantic model
transactions_schema = {
    'public.users': {
        'columns': ['id', 'email', 'password_hash', 'full_name', 'role', 'created_at'],
        'types': {
            'id': 'string',
            'email': 'string',
            'password_hash': 'string',
            'full_name': 'string',
            'role': 'string',
            'created_at': 'date'
        }
    },
    'public.transactions': {
        'columns': [
            'purchase_date', 'posted_date', 'payment_date', 'exported_date',
            'exported_datetime', 'amount', 'currency', 'original_amount',
            'original_currency', 'usd_equivalent_amount', 'expense_status',
            'payment_status', 'budget_or_limit', 'parent_budget', 'policy',
            'user', 'department', 'location', 'cost_center', 'merchant_name',
            'category', 'memo', 'type', 'current_review_assignees',
            'review_assigned_datetime', 'final_approval_datetime',
            'final_approver', 'final_copilot_approver', 'id',
            'country_of_expense'
        ],
        'types': {
            'purchase_date': 'date',
            'posted_date': 'string',
            'payment_date': 'string',
            'exported_date': 'string',
            'exported_datetime': 'string',
            'amount': 'number',
            'currency': 'string',
            'original_amount': 'number',
            'original_currency': 'string',
            'usd_equivalent_amount': 'number',
            'expense_status': 'string',
            'payment_status': 'string',
            'budget_or_limit': 'string',
            'parent_budget': 'string',
            'policy': 'string',
            'user': 'string',
            'department': 'string',
            'location': 'string',
            'cost_center': 'string',
            'merchant_name': 'string',
            'category': 'string',
            'memo': 'string',
            'type': 'string',
            'current_review_assignees': 'string',
            'review_assigned_datetime': 'string',
            'final_approval_datetime': 'string',
            'final_approver': 'string',
            'final_copilot_approver': 'string',
            'id': 'string',
            'country_of_expense': 'string'
        }
    },
    'public.transaction_locations': {
        'columns': [
            'id', 'name', 'host_id', 'host_name', 'neighbourhood_group',
            'neighbourhood', 'latitude', 'longitude', 'room_type', 'price',
            'minimum_nights', 'number_of_reviews', 'last_review',
            'reviews_per_month', 'calculated_host_listings_count',
            'availability_365', 'number_of_reviews_ltm', 'city'
        ],
        'types': {
            'id': 'number',
            'name': 'string',
            'host_id': 'number',
            'host_name': 'string',
            'neighbourhood_group': 'string',
            'neighbourhood': 'string',
            'latitude': 'number',
            'longitude': 'number',
            'room_type': 'string',
            'price': 'number',
            'minimum_nights': 'number',
            'number_of_reviews': 'number',
            'last_review': 'string',
            'reviews_per_month': 'number',
            'calculated_host_listings_count': 'number',
            'availability_365': 'number',
            'number_of_reviews_ltm': 'number',
            'city': 'string'
        }
    },
    'public.transaction_locations_2': {
        'columns': [
            'id', 'name', 'host_id', 'host_name', 'neighbourhood_group',
            'neighbourhood', 'latitude', 'longitude', 'room_type', 'price',
            'minimum_nights', 'number_of_reviews', 'last_review',
            'reviews_per_month', 'calculated_host_listings_count',
            'availability_365', 'number_of_reviews_ltm', 'city'
        ],
        'types': {
            'id': 'number',
            'name': 'string',
            'host_id': 'number',
            'host_name': 'string',
            'neighbourhood_group': 'string',
            'neighbourhood': 'string',
            'latitude': 'number',
            'longitude': 'number',
            'room_type': 'string',
            'price': 'number',
            'minimum_nights': 'number',
            'number_of_reviews': 'number',
            'last_review': 'string',
            'reviews_per_month': 'number',
            'calculated_host_listings_count': 'number',
            'availability_365': 'number',
            'number_of_reviews_ltm': 'number',
            'city': 'string'
        }
    }
}
