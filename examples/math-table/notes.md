# Entropy notes

A symbol with probability $p$ costs $\log_2 \frac{1}{p}$ bits. A coin that lands heads
three times in four costs about 0.415 bits for heads and $2$ bits for tails. A ticket
that costs $5 to $10 is not math.

Averaging the cost over every outcome gives the entropy:

$$
H(X) = \sum_i p_i \log_2 \frac{1}{p_i}
$$

| Code | bits per digit | note |
|:-----|---------------:|------|
| BCD | 4.0 | fixed 4-bit code |
| Huffman | 3.4 | whole bits only |
| Huffman on pairs | 3.36 | 100 symbols |
| Shannon limit | 3.3219 | $\log_2 10$ |
