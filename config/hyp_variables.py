hyp_variables = {
    'accounts_predictive' :
        [
            'amount',
            'transaction_cost',
            'block_time',
            'balance',
            'difficulty',
            'mining_reward',
            'nrg_reward',
            'num_transactions',
            'hash_power',
            'russell_close',
            'russell_volume',
            'sp_close',
            'sp_volume',
            'aion_volume',
            'aion_market_cap',
            'aion_close',
            'bitcoin_volume',
            'bitcoin_market_cap',
            'bitcoin_close',
            'ethereum_volume',
            'ethereum_market_cap',
            'ethereum_close',
            'aion_fork',
            'aion_push',
            'aion_release',
        ]
}
groupby_dict = {}
groupby_dict['accounts_predictive'] = {
            'amount':'mean',
            'transaction_cost':'mean',
            'block_time':'mean',
            'balance':'mean',
            'difficulty':'mean',
            'mining_reward':'mean',
            'nrg_reward':'mean',
            'num_transactions':'mean',
            'hash_power':'mean',
            'russell_close':'mean',
            'russell_volume':'mean',
            'sp_close':'mean',
            'sp_volume':'mean',
            'aion_volume':'mean',
            'aion_market_cap':'mean',
            'aion_close':'mean',
            'bitcoin_volume':'mean',
            'bitcoin_market_cap':'mean',
            'bitcoin_close':'mean',
            'ethereum_volume':'mean',
            'ethereum_market_cap':'mean',
            'ethereum_close':'mean',
            'aion_fork':'mean',
            'aion_push':'mean',
            'aion_release':'mean',
}

groupby_dict['crypto_modelling'] = {
            'russell_close':'mean',
            'russell_volume':'mean',
            'sp_close':'mean',
            'sp_volume':'mean',
}