# The voice: what it says by itself, and what you must spell out

Part of the instructions in `SKILL.md`. Read this when a sentence of narration holds anything that is not
plain words (notation, a symbol, an identifier, a file name, an unusual name), or when `check` warns that the
voice cannot say something. You cannot listen to the result, so this is how you get it right without hearing it.

`say` is what the caption shows; the voice gets the same sentence unless you add `speak`. The caption always
keeps what you wrote in `say`.

## 1. Formulas and notation

- Say a formula in words ("H of X given Y", "the sum over n of x to the n"). Never put LaTeX in `say`. Short notation is read aloud for you, and the caption keeps what you wrote: `a - b`, `x^2`, `x_i`, `10^-3`, `1/2`, `dy/dx`, `f(x)`, `f'(x)`, `|x|`, `n!`, `x > 0`, and signs such as ∈ → ∂ ∑ ⇒ and ². Anything longer (a nested fraction, a sum with limits) will not come out right: write it in words. The check warns when a sentence still holds something the voice cannot say.
- Ordinals of a letter are read correctly without help: "n-th", "i-th", "k-th", "nth" and "(n+1)-th" are spoken as "enth", "eyeth", "kayth", "enth" and "n plus first". Write them as usual; the caption keeps your spelling.
- Write "sine", not "sin", when it stands alone in a sentence.

## 2. Identifiers, paths and names

- The voice mispronounces identifiers, paths and symbols. When a sentence needs one, keep `say` as it should appear in the caption and add `speak` with how to pronounce it: `"say": "It calls parse_args() first."`, `"speak": "It calls parse args first."`
- Acronyms in capitals are spelled out letter by letter (HTTP, URL, API, TLS), and numbers are read as numbers, so those need no `speak`. Made-up and mixed-case names often go wrong. You cannot listen, but you can look: `python -m idr sounds "PyPI" "memtable"` prints the sounds of each in IPA (here `pˈaɪ pˈaɪ`, "pie pie", and `mˈɛmtəbəl`, "mem-tuh-bul"; `aɪ` is "eye", `eɪ` is "ay", `iː` is "ee", `ə` is "uh"), and you can try a respelling the same way (`"pie pee eye"`, `"mem table"`) before putting it in `speak`.
- Terms and names the voice would otherwise get wrong are read correctly without help too: sinh, tanh, arctan, xi, eigenvalue, QED, and mathematicians such as Cauchy, Leibniz, Lebesgue, Noether, Poincaré, Poisson, Bernoulli, Dirichlet, Lagrange, Laplace, Fermat, Descartes, Erdős and L'Hôpital. The letter `a` is said as a letter where it is a quantity ("x minus a", "at a,") and as the article elsewhere; a capital A that is a name ("call it A of x", "A'(x)", "the matrix A") is said as the letter too. For any other name, check it with `python -m idr sounds "Name"` and add it to `pronounce` if it comes out wrong.

## 3. One name, many sentences

- For a name that comes up again and again, give its pronunciation once at the top of the storyboard instead of a `speak` on every beat: `"pronounce": { "PyPI": "pie pee eye", "memtable": "mem table" }`. It applies to every sentence (whole words, matching capitals), and a `.i-dont-read.json` in `--root` can hold a `pronounce` table for the whole project.

## 4. When the check warns

`check` names the sentence and what in it the voice cannot say. Reword `say` in plain words if the caption
can lose the notation; otherwise keep `say` and add `speak`. Then run `python -m idr sounds "the sentence"`
to see what the voice will get.
