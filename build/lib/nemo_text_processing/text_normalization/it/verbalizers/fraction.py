# Copyright (c) 2022, NVIDIA CORPORATION & AFFILIATES.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import pynini
from nemo_text_processing.text_normalization.en.graph_utils import (
    NEMO_CHAR,
    NEMO_NOT_QUOTE,
    NEMO_NOT_SPACE,
    NEMO_SIGMA,
    NEMO_SPACE,
    GraphFst,
    delete_space,
    insert_space,
)
from nemo_text_processing.text_normalization.it.graph_utils import (
    accents,
    shift_cardinal_gender,
    strip_cardinal_apocope,
)
from pynini.lib import pynutil


class FractionFst(GraphFst):
    """
	Finite state transducer for verbalizing fraction
		e.g. tokens { fraction { integer: "treinta y tres" numerator: "cuatro" denominator: "quinto" } } ->
            treinta y tres y cuatro quintos


	Args:
		deterministic: if True will provide a single transduction option,
			for False multiple transduction are generated (used for audio-based normalization)
	"""

    def __init__(self, deterministic: bool = True):
        super().__init__(name="fraction", kind="verbalize", deterministic=deterministic)

        # Derivational strings append 'avo' as a suffix. Adding space for processing aid
        plural = pynutil.delete("o") + pynutil.insert("i")
        conjunction = pynutil.insert(" e ")

        integer = (
            pynutil.delete("integer_part: \"")
            + strip_cardinal_apocope(pynini.closure(NEMO_NOT_QUOTE))
            + pynutil.delete("\"")
        )

        numerator_one = pynutil.delete("numerator: \"") + pynini.accep("un") + pynutil.delete("\" ")
        numerator = (
            pynutil.delete("numerator: \"")
            + pynini.difference(pynini.closure(NEMO_NOT_QUOTE), "un")
            + pynutil.delete("\" ")
        )

        denominator_add_stem = pynutil.delete("denominator: \"") + (
            pynini.closure(NEMO_NOT_QUOTE)
            + pynutil.delete("\" morphosyntactic_features: \"add_root\"")
        )
        denominator_ordinal = pynutil.delete("denominator: \"") + (
            pynini.closure(NEMO_NOT_QUOTE) + pynutil.delete("\" morphosyntactic_features: \"ordinal\"")
        )
        denominator_cardinal = pynutil.delete("denominator: \"") + (
            pynini.closure(NEMO_NOT_QUOTE) + pynutil.delete("\"")
        )

        denominator_singular = pynini.union(denominator_add_stem, denominator_ordinal)
        denominator_plural = denominator_singular + plural

        # Merging operations
        merge = pynini.cdrewrite(
            pynini.cross(" e ", "i"), "", "", NEMO_SIGMA
        )  # The denominator must be a single word, with the conjunction "y" replaced by i
        merge @= pynini.cdrewrite(delete_space, "", pynini.difference(NEMO_CHAR, "parte"), NEMO_SIGMA)

        # The merger can produce duplicate vowels. This is not allowed in orthography
        delete_duplicates = pynini.string_map([("aa", "a"), ("oo", "o")])  # Removes vowels
        delete_duplicates = pynini.cdrewrite(delete_duplicates, "", "", NEMO_SIGMA)

        remove_accents = pynini.cdrewrite(
            accents,
            pynini.union(NEMO_SPACE, pynini.accep("[BOS]")) + pynini.closure(NEMO_NOT_SPACE),
            pynini.closure(NEMO_NOT_SPACE) + pynini.union("esimo", "esima"),
            NEMO_SIGMA,
        )
        merge_into_single_word = merge @ remove_accents @ delete_duplicates

        fraction_default = numerator + delete_space + insert_space + (denominator_plural @ merge_into_single_word)

        fraction_with_one = (
            numerator_one + delete_space + insert_space + (denominator_singular @ merge_into_single_word)
        )

        fraction_with_cardinal = strip_cardinal_apocope(numerator | numerator_one)
        fraction_with_cardinal += (
            delete_space + pynutil.insert(" fratto ") + strip_cardinal_apocope(denominator_cardinal)
        )

        fraction_with_one @= pynini.cdrewrite(
            pynini.cross("un mezzo", "mezzo"), "", "", NEMO_SIGMA
        )  # "medio" not "un medio"

        fraction = fraction_with_one | fraction_default | fraction_with_cardinal
        graph_masc = pynini.closure(integer + delete_space + conjunction, 0, 1) + fraction

        # Manage cases of fem gender (only shows on integer except for "medio")
        integer_fem = shift_cardinal_gender(integer)
        fraction_default |= (
            shift_cardinal_gender(numerator)
            + delete_space
            + insert_space
            + (denominator_plural @ pynini.cross("mezzo", "mezza"))
        )
        fraction_with_one |= (
            pynutil.delete(numerator_one) + delete_space + (denominator_singular @ pynini.cross("mezzo", "mezza"))
        )

        fraction_fem = fraction_with_one | fraction_default | fraction_with_cardinal
        graph_fem = pynini.closure(integer_fem + delete_space + conjunction, 0, 1) + fraction_fem

        self.graph_masc = pynini.optimize(graph_masc)
        self.graph_fem = pynini.optimize(graph_fem)

        self.graph = graph_masc | graph_fem

        delete_tokens = self.delete_tokens(self.graph)
        self.fst = delete_tokens.optimize()
