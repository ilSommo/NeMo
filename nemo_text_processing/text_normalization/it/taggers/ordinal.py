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
    NEMO_SIGMA,
    NEMO_SPACE,
    GraphFst,
    delete_space,
)
from nemo_text_processing.text_normalization.it.graph_utils import strip_accent
from nemo_text_processing.text_normalization.it.utils import get_abs_path
from pynini.lib import pynutil

digit = pynini.invert(pynini.string_file(get_abs_path("data/ordinals/digit.tsv")))
teens = pynini.invert(pynini.string_file(get_abs_path("data/ordinals/teen.tsv")))
twenties = pynini.invert(pynini.string_file(get_abs_path("data/ordinals/twenties.tsv")))
ties = pynini.invert(pynini.string_file(get_abs_path("data/ordinals/ties.tsv")))
hundreds = pynini.invert(pynini.string_file(get_abs_path("data/ordinals/hundreds.tsv")))


def get_one_to_one_thousand(cardinal: 'pynini.FstLike') -> 'pynini.FstLike':
    """
    Produces an acceptor for verbalizations of all numbers from 1 to 1000. Needed for ordinals and fractions.

    Args:
        cardinal: CardinalFst

    Returns:
        fst: A pynini.FstLike object
    """
    numbers = pynini.string_map([str(_) for _ in range(1, 1000)]) @ cardinal
    return pynini.project(numbers, "output").optimize()


class OrdinalFst(GraphFst):
    """
    Finite state transducer for classifying ordinal
        	"21.º" -> ordinal { integer: "vigésimo primero" morphosyntactic_features: "gender_masc" }
    This class converts ordinal up to the millionth (millonésimo) order (exclusive).

    This FST also records the ending of the ordinal (called "morphosyntactic_features"):
    either as gender_masc, gender_fem, or apocope. Also introduces plural feature for non-deterministic graphs.

    Args:
        cardinal: CardinalFst
        deterministic: if True will provide a single transduction option,
            for False multiple transduction are generated (used for audio-based normalization)
    """

    def __init__(self, cardinal: GraphFst, deterministic: bool = True):
        super().__init__(name="ordinal", kind="classify")
        cardinal_graph = cardinal.graph

        graph_digit = digit.optimize()
        graph_teens = teens.optimize()
        graph_ties = ties.optimize()
        graph_twenties = twenties.optimize()
        graph_hundreds = hundreds.optimize()

        graph_tens_component = (
            graph_teens
            | (graph_ties + pynini.closure(graph_digit, 0, 1))
            | graph_twenties
        )

        graph_hundred_component = pynini.union(
            graph_hundreds + pynini.closure(NEMO_SPACE + pynini.union(graph_tens_component, graph_digit), 0, 1),
            graph_tens_component,
            graph_digit,
        )

        # Need to go up to thousands for fractions
        self.one_to_one_thousand = get_one_to_one_thousand(cardinal_graph)

        thousands = pynini.cross("mille", "millesimo")

        graph_thousands = (
            strip_accent(self.one_to_one_thousand) + NEMO_SPACE + thousands
        )  # Cardinals become prefix for thousands series. Snce accent on the powers of ten we strip accent from leading words
        graph_thousands @= pynini.cdrewrite(delete_space, "", "millesimo", NEMO_SIGMA)  # merge as a prefix
        graph_thousands |= thousands

        self.multiples_of_thousand = (cardinal_graph @ graph_thousands).optimize()

        if (
            not deterministic
        ):  # Formally the words preceding the power of ten should be a prefix, but some maintain word boundaries.
            graph_thousands |= (self.one_to_one_thousand @ graph_hundred_component) + NEMO_SPACE + thousands

        graph_thousands += pynini.closure(NEMO_SPACE + graph_hundred_component, 0, 1)

        ordinal_graph = graph_thousands | graph_hundred_component
        ordinal_graph = cardinal_graph @ ordinal_graph

        if not deterministic:
            # The 10's and 20's series can also be two words
            split_words = pynini.cross("decimo", "decimo ") | pynini.cross("ventesimo", "ventesimo ")
            split_words = pynini.cdrewrite(split_words, "", NEMO_CHAR, NEMO_SIGMA)
            ordinal_graph |= ordinal_graph @ split_words

        # If "octavo" is preceeded by the "o" within string, it needs deletion
        ordinal_graph @= pynini.cdrewrite(pynutil.delete("o"), "", "ottavo", NEMO_SIGMA)

        self.graph = ordinal_graph.optimize()

        masc = pynini.accep("gender_masc")
        fem = pynini.accep("gender_fem")
        apocope = pynini.accep("apocope")

        delete_period = pynini.closure(pynutil.delete("."), 0, 1)  # Sometimes the period is omitted f

        accept_masc = delete_period + pynini.cross("º", masc)
        accep_fem = delete_period + pynini.cross("ª", fem)
        accep_apocope = delete_period + pynini.cross("ᵉʳ", apocope)

        # Rest of graph
        convert_abbreviation = accept_masc | accep_fem | accep_apocope

        graph = (
            pynutil.insert("integer: \"")
            + ordinal_graph
            + pynutil.insert("\"")
            + pynutil.insert(" morphosyntactic_features: \"")
            + convert_abbreviation
            + pynutil.insert("\"")
        )
        
        final_graph = self.add_tokens(graph)
        self.fst = final_graph.optimize()
