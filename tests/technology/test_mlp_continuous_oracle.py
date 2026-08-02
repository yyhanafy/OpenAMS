from openams.technology.ml_continuous_oracle import AdaptiveMosCache
def test_cache_key_stable():
 assert AdaptiveMosCache.key_for(polarity='nmos',width_um=1.0)==AdaptiveMosCache.key_for(width_um=1.0,polarity='nmos')
