###############################################################################
#
# Copyright 2020, University of Stuttgart: Institute for Natural Language Processing (IMS)
#
# This file is part of Adviser.
# Adviser is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3.
#
# Adviser is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Adviser.  If not, see <https://www.gnu.org/licenses/>.
#
###############################################################################

from collections import defaultdict
import json
import os
from typing import List, Dict

from services.service import PublishSubscribe
from services.service import Service
from utils import SysAct, SysActionType
from utils.beliefstate import BeliefState
from utils.domain.jsonlookupdomain import JSONLookupDomain
from utils.logger import DiasysLogger
from utils.useract import UserActionType


class HandcraftedPolicy(Service):
    """ Base class for handcrafted policies.

    Provides a simple rule-based policy. Can be used for any domain where a user is
    trying to find an entity (eg. a course from a module handbook) from a database
    by providing constraints (eg. semester the course is offered) or where a user is
    trying to find out additional information about a named entity.

    Output is a system action such as:
     * `inform`: provides information on an entity
     * `request`: request more information from the user
     * `bye`: issue parting message and end dialog

    In order to create your own policy, you can inherit from this class.
    Make sure to overwrite the `choose_sys_act`-method with whatever additionally
    rules/functionality required.

    """

    def __init__(self, domain: JSONLookupDomain, logger: DiasysLogger = DiasysLogger(),
                 max_turns: int = 25):
        """
        Initializes the policy

        Arguments:
            domain {domain.jsonlookupdomain.JSONLookupDomain} -- Domain

        """
        self.first_turn = True
        Service.__init__(self, domain=domain)
        self.current_suggestions = []  # list of current suggestions
        self.s_index = 0  # the index in current suggestions for the current system reccomendation
        self.domain_key = domain.get_primary_key()
        self.logger = logger
        self.max_turns = max_turns

    def dialog_start(self):
        """
            resets the policy after each dialog
        """
        self.turns = 0
        self.first_turn = True
        self.current_suggestions = []  # list of current suggestions
        self.s_index = 0  # the index in current suggestions for the current system reccomendation

    @PublishSubscribe(sub_topics=["beliefstate"], pub_topics=["sys_act", "sys_state"])
    def choose_sys_act(self, beliefstate: BeliefState) \
            -> dict(sys_act=SysAct):

        """
            Responsible for walking the policy through a single turn. Uses the current user
            action and system belief state to determine what the next system action should be.

            To implement an alternate policy, this method may need to be overwritten

            Args:
                belief_state (BeliefState): a BeliefState obejct representing current system
                                           knowledge

            Returns:
                (dict): a dictionary with the key "sys_act" and the value that of the systems next
                        action

        """
        self.turns += 1
        # do nothing on the first turn --LV
        sys_state = {}
        if self.first_turn and not beliefstate['user_acts']:
            self.first_turn = False
            sys_act = SysAct()
            sys_act.type = SysActionType.Welcome
            sys_state["last_act"] = sys_act
            return {'sys_act': sys_act, "sys_state": sys_state}

        elif self.first_turn and UserActionType.NewDialogue in beliefstate["user_acts"]:
            self.first_turn = False
            sys_act = SysAct()
            sys_act.type = SysActionType.Welcome
            sys_state["last_act"] = sys_act
            return {'sys_act': sys_act, "sys_state": sys_state}

        # Handles case where it was the first turn, but there are user acts
        elif self.first_turn:
            self.first_turn = False

        if self.turns >= self.max_turns:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bye
            sys_state["last_act"] = sys_act
            return {'sys_act': sys_act, "sys_state": sys_state}

        # removes hello and thanks if there are also domain specific actions
        self._remove_gen_actions(beliefstate)

        if UserActionType.Bad in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bad
        # if the action is 'bye' tell system to end dialog
        elif UserActionType.Bye in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bye
        # if user only says thanks, ask if they want anything else
        elif UserActionType.Thanks in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.RequestMore
            
        ### new acts ####

        elif UserActionType.NewDialogue in beliefstate["user_acts"]:
            # if the user wants to start a new dialogue
            sys_act = SysAct()
            sys_act.type = SysActionType.Welcome
            os.system('cls' if os.name == 'nt' else 'clear') # clear terminal output
            self.dialog_start()

        # If user only says hello, guide user for more information
        elif UserActionType.Hello in beliefstate["user_acts"] or UserActionType.SelectDomain in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.GuideUser

        elif UserActionType.GiveRating in beliefstate["user_acts"]:
            # if the user wants to give a rating
            sys_act = SysAct()
            # check if a restaurant/bar is in the beliefstate or has been suggested to the user
            if self._get_name(beliefstate):
                #print("primary key:", self.domain.get_primary_key(), "name:", self._get_name(beliefstate))
                sys_act.add_value(self.domain.get_primary_key(), self._get_name(beliefstate))
                sys_act.add_value(slot='ratings_givable', value=beliefstate['given_rating'])
                sys_act.type = SysActionType.ConfirmGiveRating
                # modify rating value in the database
                self._modfiy_db(beliefstate)
            else:
                # ask for which restaurant/bar the user wants to give a rating
                sys_act.type = SysActionType.Request
                sys_act.add_value(slot='name')
        
        elif UserActionType.WriteReview in beliefstate["user_acts"]:
            # if the user wants to write a review
            sys_act = SysAct()
            # check if a restaurant/bar is in the beliefstate or has been suggested to the user
            if self._get_name(beliefstate):
                sys_act.add_value(self.domain.get_primary_key(), self._get_name(beliefstate))
                sys_act.type = SysActionType.AskWriteReview
                sys_state['last_act'] = sys_act
            else:
                # ask for which restaurant/bar the user wants to give a rating
                sys_act.type = SysActionType.Request
                sys_act.add_value(slot='name')
        
        elif UserActionType.WrittenReview in beliefstate["user_acts"]:
            # if the user has entered a review
            sys_act = SysAct()
            sys_act.add_value(self.domain.get_primary_key(), self._get_name(beliefstate))
            sys_act.add_value(slot='review', value=beliefstate['review'])
            sys_act.type = SysActionType.ConfirmWriteReview
            # modify the reviews in the database
            self._modfiy_db(beliefstate)
        
        elif UserActionType.AskDistance in beliefstate["user_acts"]:
            sys_act = SysAct()
            # check if a restaurant/bar is in the beliefstate or has been suggested to the user
            if self._get_name(beliefstate):
                sys_act.type = SysActionType.AskStartPoint
                sys_state['last_act'] = sys_act
            else:
                # ask for which restaurant/bar the user wants to give a rating
                sys_act.type = SysActionType.Request
                sys_act.add_value(slot='name')
        
        elif UserActionType.InformStartPoint in beliefstate["user_acts"]:
            sys_act = SysAct()
            # save the informed staring point to the beliefstate to be used later
            start_point = self._save_start_point(beliefstate)
            sys_act.type = SysActionType.AskDistanceManner
            sys_state['last_act'] = sys_act

        elif UserActionType.InformDistanceManner in beliefstate["user_acts"]:
            # if the user has given how to get there (by foot, by bike, by car)
            #traveling_manner = self._save_travel_manner(beliefstate)
            sys_act = SysAct()
            # calculate distance and duration
            distance, duration = self._calculate_distance_duration(beliefstate)
            # if the given address or the address of the restaurant is incorrect or not given
            if distance == 'BadTravelManner' and duration == 'BadTravelManner':
                sys_act.type = SysActionType.BadTravelManner
                sys_state['last_act'] = sys_act
            elif distance is None and duration is None:
                sys_act.type = SysActionType.BadAddress
                sys_state['last_act'] = sys_act
            else:
                sys_act.add_value(self.domain.get_primary_key(), self._get_name(beliefstate))
                #sys_act.add_value(slot='start_point', value=beliefstate['start_point'])
                sys_act.add_value(slot='distance_manner', value=beliefstate['distance_manner'])
                sys_act.add_value(slot='distance', value=distance)
                sys_act.add_value(slot='duration', value=duration)
                sys_act.type = SysActionType.InformDistance
                
        elif UserActionType.AskOpeningDay in beliefstate["user_acts"]:
            sys_act = SysAct()
            # check if a restaurant/bar is in the beliefstate or has been suggested to the user
            if self._get_name(beliefstate):
                # query opening days and get information for requested day
                opening_info = self._query_opening_info(beliefstate)
                sys_act.add_value(self.domain.get_primary_key(), self._get_name(beliefstate))
                sys_act.add_value(slot='opening_day', value=beliefstate['req_openingday'])
                sys_act.add_value(slot='opening_info', value=opening_info)
                sys_act.type = SysActionType.InformOpeningDay
            else:
                # ask for the restaurant/bar
                sys_act.type = SysActionType.Request
                sys_act.add_value(slot='name')
            
        elif UserActionType.AskManner in beliefstate["user_acts"]:
            sys_act = SysAct()
            # check if a restaurant/bar is in the beliefstate or has been suggested to the user
            if self._get_name(beliefstate):
                # query manner and get information for requested manner
                manner_info = self._query_manner_info(beliefstate)
                sys_act.add_value(self.domain.get_primary_key(), self._get_name(beliefstate))
                sys_act.add_value(slot='manner_info', value=manner_info)
                sys_act.type = SysActionType.InformManner
            else:
                # ask for the restaurant/bar
                sys_act.type = SysActionType.Request
                sys_act.add_value(slot='name')
        
        elif UserActionType.NegativeInform in beliefstate["user_acts"]:
            sys_act = SysAct()
            sys_act.type = SysActionType.WhatDoYouWant
        
        # If user only says hello, request a random slot to move dialog along
        elif UserActionType.Hello in beliefstate["user_acts"] or UserActionType.SelectDomain in beliefstate["user_acts"]:
            # as long as there are open slots, choose one randomly
            if self._get_open_slot(beliefstate):
                sys_act = SysAct()
                sys_act.type = SysActionType.Request
                slot = self._get_open_slot(beliefstate)
                sys_act.add_value(slot)

            # If there are no more open slots, ask the user if you can help with anything else since
            # this can only happen in the case an offer has already been made --LV
            else:
                sys_act = SysAct()
                sys_act.type = SysActionType.RequestMore

            # If we switch to the domain, start a new dialog
            if UserActionType.SelectDomain in beliefstate["user_acts"]:
                self.dialog_start()
            self.first_turn = False
        # handle domain specific actions
        else:
            sys_act, sys_state = self._next_action(beliefstate)
        if self.logger:
            self.logger.dialog_turn("System Action: " + str(sys_act))
        if "last_act" not in sys_state:
            sys_state["last_act"] = sys_act
        return {'sys_act': sys_act, "sys_state": sys_state}

    def _remove_gen_actions(self, beliefstate: BeliefState):
        """
            Helper function to read through user action list and if necessary
            delete filler actions (eg. Hello, thanks) when there are other non-filler
            (eg. Inform, Request) actions from the user. Stores list of relevant actions
            as a class variable

            Args:
                beliefstate (BeliefState): BeliefState object - includes list of all
                                           current UserActionTypes

        """
        act_types_lst = beliefstate["user_acts"]
        # These are filler actions, so if there are other non-filler acions, remove them from
        # the list of action types
        while len(act_types_lst) > 1:
            if UserActionType.Thanks in act_types_lst:
                act_types_lst.remove(UserActionType.Thanks)
            elif UserActionType.Bad in act_types_lst:
                act_types_lst.remove(UserActionType.Bad)
            elif UserActionType.Hello in act_types_lst:
                act_types_lst.remove(UserActionType.Hello)
            else:
                break

    def _modfiy_db(self, beliefstate: BeliefState):
        """Use the domain to update the database for the specified restaurant/bar and slot

        Args:
            beliefstate (BeliefState): BeliefState object; contains all given user constraints to date
        """
        # modify the rating or the reviews
        if beliefstate['given_rating']:
            given_rating = float(beliefstate['given_rating'])
            #print("(policy.py) given_rating:", given_rating)
            self.domain.enter_rating(given_rating, self._get_name(beliefstate))
        if beliefstate['review']:
            review = beliefstate['review']
            review = review.replace("'", ' ').replace("\"", ' ')
            self.domain.enter_review(review, self._get_name(beliefstate))
    
    def _save_start_point(self, beliefstate: BeliefState):
        """
        save start point which will be used in the next
        """
        start_point = beliefstate['start_point']
        return start_point

    def _delete_error_travel_manner(self, beliefstate: BeliefState):
        beliefstate['distance_manner'] = ''
        #return traveling_manner
    
    def _calculate_distance_duration(self, beliefstate: BeliefState):
        """Use domain to get the address of the restaurant and calculate the distance and duration

        Args:
            beliefstate (BeliefState): BeliefState object; contains all given user constraints to date

        Returns:
            str, str: distance, duration 
        """
        start_point = self._save_start_point(beliefstate)
        distance_manner = beliefstate['distance_manner']
        distance, duration = self.domain.distance_duration(start_point, self._get_name(beliefstate), distance_manner)
        return distance, duration
    
    def _query_opening_info(self, beliefstate: BeliefState):
        """Extract information about the requested day from the opening hours in the database

        Args:
            beliefstate (BeliefState): BeliefState object; contains all given user constraints to date

        Returns:
            str: opening information
        """
        req_openingday = beliefstate['req_openingday']
        opening_info = self.domain.query_opening_info(req_openingday, self._get_name(beliefstate))
        return opening_info

    def _query_manner_info(self, beliefstate: BeliefState):
        """Extract information about the requested manner from the manners in the database

        Args:
            beliefstate (BeliefState): BeliefState object; contains all given user constraints to date

        Returns:
            str: manner information
        """
        req_manner = beliefstate['req_manner']
        manner_info = self.domain.query_manner_info(req_manner, self._get_name(beliefstate))
        return manner_info

    def _query_db(self, beliefstate: BeliefState):
        """Based on the constraints specified, uses the domain to generate the appropriate type
           of query for the database

        Args:
            beliefstate (BeliefState): BeliefState object; contains all given user constraints to date

        Returns:
            iterable: representing the results of the database lookup

        --LV
        """
        # determine if an entity has already been suggested or was mentioned by the user
        name = self._get_name(beliefstate)
        # if yes and the user is asking for info about a specific entity, generate a query to get
        # that info for the slots they have specified
        if name and beliefstate['requests']:
            requested_slots = beliefstate['requests']
            return self.domain.find_info_about_entity(name, requested_slots)
        # otherwise, issue a query to find all entities which satisfy the constraints the user
        # has given so far
        else:
            constraints, _ = self._get_constraints(beliefstate)
            return self.domain.find_entities(constraints)
    
    def _get_name(self, beliefstate: BeliefState):
        """Finds if an entity has been suggested by the system (in the form of an offer candidate)
           or by the user (in the form of an InformByName act). If so returns the identifier for
           it, otherwise returns None

        Args:
            beliefstate (BeliefState): BeliefState object, contains all known user informs

        Return:
            (str): Returns a string representing the current entity name

        -LV
        """
        name = None
        prim_key = self.domain.get_primary_key()
        if prim_key in beliefstate['informs']:
            possible_names = beliefstate['informs'][prim_key]
            if possible_names == {}:
                name = None
            else:
                name = sorted(possible_names.items(), key=lambda kv: kv[1], reverse=True)[0][0]
        # if the user is tyring to query by name
        else:
            if self.s_index < len(self.current_suggestions):
                current_suggestion = self.current_suggestions[self.s_index]
                if current_suggestion:
                    name = current_suggestion[self.domain_key]
        return name

    def _get_constraints(self, beliefstate: BeliefState):
        """Reads the belief state and extracts any user specified constraints and any constraints
           the user indicated they don't care about, so the system knows not to ask about them

        Args:
            beliefstate (BeliefState): BeliefState object; contains all user constraints to date

        Return:
            (tuple): dict of user requested slot names and their values and list of slots the user
                     doesn't care about

        --LV
        """
        slots = {}
        # parts of the belief state which don't contain constraints
        dontcare = [slot for slot in beliefstate['informs'] if "dontcare" in beliefstate["informs"][slot]]
        informs = beliefstate["informs"]
        slots = {}
        # TODO: consider threshold of belief for adding a value? --LV
        for slot in informs:
            if slot not in dontcare:
                for value in informs[slot]:
                    # save values as lists to be able to handle multiple values
                    if slot not in slots:
                        slots[slot] = []
                    slots[slot].append(value)
        return slots, dontcare

    def _get_open_slot(self, beliefstate: BeliefState):
        """For a hello statement we need to be able to figure out what slots the user has not yet
           specified constraint for, this method returns one of those at random

        Args:
            beliefstate (BeliefState): BeliefState object; contains all user constraints to date

        Returns:
            (str): a string representing a category the system might want more info on. If all
            system requestables have been filled, return none

        """
        filled_slots, _ = self._get_constraints(beliefstate)
        requestable_slots = self.domain.get_system_requestable_slots()
        for slot in requestable_slots:
            if slot not in filled_slots:
                return slot
        return None

    def _next_action(self, beliefstate: BeliefState):
        """Determines the next system action based on the current belief state and
           previous action.

           When implementing a new type of policy, this method MUST be rewritten

        Args:
            beliefstate (BeliefState): BeliefState object; contains all user constraints to date
            of each possible state

        Return:
            (SysAct): the next system action

        --LV
        """
        sys_state = {}
        # Assuming this happens only because domain is not actually active --LV
        if UserActionType.Bad in beliefstate['user_acts'] or beliefstate['requests'] \
                and not self._get_name(beliefstate):
            sys_act = SysAct()
            sys_act.type = SysActionType.Bad
            return sys_act, {'last_act': sys_act}

        elif UserActionType.RequestAlternatives in beliefstate['user_acts'] \
                and not self._get_constraints(beliefstate)[0]:
            sys_act = SysAct()
            sys_act.type = SysActionType.Bad
            return sys_act, {'last_act': sys_act}

        elif self.domain.get_primary_key() in beliefstate['informs'] \
                and not beliefstate['requests']:
            sys_act = SysAct()
            sys_act.type = SysActionType.InformByName
            sys_act.add_value(self.domain.get_primary_key(), self._get_name(beliefstate))
            return sys_act, {'last_act': sys_act}

        # Otherwise we need to query the db to determine next action
        results = self._query_db(beliefstate)
        sys_act = self._raw_action(results, beliefstate)

        # requests are fairly easy, if it's a request, return it directly
        if sys_act.type == SysActionType.Request:
            if len(list(sys_act.slot_values.keys())) > 0:
                sys_state['lastRequestSlot'] = list(sys_act.slot_values.keys())[0]

        # otherwise we need to convert a raw inform into a one with proper slots and values
        elif sys_act.type == SysActionType.InformByName:
            self._convert_inform(results, sys_act, beliefstate)
            # update belief state to reflect the offer we just made
            values = sys_act.get_values(self.domain.get_primary_key())
            if values:
                # belief_state['system']['lastInformedPrimKeyVal'] = values[0]
                sys_state['lastInformedPrimKeyVal'] = values[0]
            else:
                sys_act.add_value(self.domain.get_primary_key(), 'none')

        sys_state['last_act'] = sys_act
        return (sys_act, sys_state)

    def _raw_action(self, q_res: iter, beliefstate: BeliefState) -> SysAct:
        """Based on the output of the db query and the method, choose
           whether next action should be request or inform

        Args:
            q_res (list): rows (list of dicts) returned by the issued sqlite3 query
            beliefstate (BeliefState): contains all UserActionTypes for the current turn

        Returns:
            (SysAct): SysAct object of appropriate type

        --LV
        """
        sys_act = SysAct()
        # if there is more than one result
        if len(q_res) > 1 and not beliefstate['requests']:
            constraints, dontcare = self._get_constraints(beliefstate)
            # Gather all the results for each column
            temp = {key: [] for key in q_res[0].keys()}
            # If any column has multiple values, ask for clarification
            for result in q_res:
                for key in result.keys():
                    if key != self.domain_key:
                        temp[key].append(result[key])
            next_req = self._gen_next_request(temp, beliefstate)
            if next_req:
                sys_act.type = SysActionType.Request
                sys_act.add_value(next_req)
                return sys_act

        # Otherwise action type will be inform, so return an empty inform (to be filled in later)
        sys_act.type = SysActionType.InformByName
        return sys_act

    def _gen_next_request(self, temp: Dict[str, List[str]], belief_state: BeliefState):
        """
            Calculates which slot to request next based asking for non-binary slotes first and then
            based on which binary slots provide the biggest reduction in the size of db results

            NOTE: If the dataset is large, this is probably not a great idea to calculate each turn
                  it's relatively simple, but could add up over time

            Args:
                temp (Dict[str, List[str]]: a dictionary with the keys and values for each result
                                            in the result set

            Returns: (str) representing the slot to ask for next (or empty if none)
        """
        req_slots = self.domain.get_system_requestable_slots()
        # don't other to cacluate statistics for things which have been specified
        constraints, dontcare = self._get_constraints(belief_state)
        # split out binary slots so we can ask about them second
        req_slots = [s for s in req_slots if s not in dontcare and s not in constraints]
        bin_slots = [slot for slot in req_slots if len(self.domain.get_possible_values(slot)) == 2]
        non_bin_slots = [slot for slot in req_slots if slot not in bin_slots]
        # check if there are any differences in values for non-binary slots,
        # if a slot has multiple values, ask about that slot
        for slot in non_bin_slots:
            if len(set(temp[slot])) > 1:
                return slot
        # Otherwise look to see if there are differnces in binary slots
        return self._highest_info_gain(bin_slots, temp)

    def _highest_info_gain(self, bin_slots: List[str], temp: Dict[str, List[str]]):
        """ Since we don't have lables, we can't properlly calculate entropy, so instead we'll go
            for trying to ask after a feature that splits the results in half as evenly as possible
            (that way we gain most info regardless of which way the user chooses)

            Args:
                bin_slots: a list of strings representing system requestable binary slots which
                           have not yet been specified
                temp (Dict[str, List[str]]: a dictionary with the keys and values for each result
                                            in the result set

            Returns: (str) representing the slot to ask for next (or empty if none)
        """
        diffs = {}
        for slot in bin_slots:
            val1, val2 = self.domain.get_possible_values(slot)
            values_dic = defaultdict(int)
            for val in temp[slot]:
                values_dic[val] += 1
            if val1 in values_dic and val2 in values_dic:
                diffs[slot] = abs(values_dic[val1] - values_dic[val2])
            # If all slots have the same value, we don't need to request anything, return none
        if not diffs:
            return ""
        sorted_diffs = sorted(diffs.items(), key=lambda kv: kv[1])
        return sorted_diffs[0][0]

    def _convert_inform(self, q_results: iter,
                        sys_act: SysAct, beliefstate: BeliefState):
        """Fills in the slots and values for a raw inform so it can be returned as the
           next system action.

        Args:
            q_results (list): Results of SQL database query
            sys_act (SysAct): the act to be modified
            beliefstate(BeliefState): BeliefState object; contains all user constraints to date and
                                      the UserActionTypes for the current turn

        --LV
        """

        if beliefstate["requests"] or self.domain.get_primary_key() in beliefstate['informs']:
            self._convert_inform_by_primkey(q_results, sys_act, beliefstate)

        elif UserActionType.RequestAlternatives in beliefstate['user_acts']:
            self._convert_inform_by_alternatives(sys_act, q_results, beliefstate)

        else:
            self._convert_inform_by_constraints(q_results, sys_act, beliefstate)

    def _convert_inform_by_primkey(self, q_results: iter,
                                   sys_act: SysAct, beliefstate: BeliefState):
        """
            Helper function that adds the values for slots to a SysAct object when the system
            is answering a request for information about an entity from the user

            Args:
                q_results (iterable): list of query results from the database
                sys_act (SysAct): current raw sys_act to be filled in
                beliefstate (BeliefState): BeliefState object; contains all user informs to date

        """
        sys_act.type = SysActionType.InformByName
        if q_results:
            result = q_results[0]  # currently return just the first result
            keys = list(result.keys())[:4]  # should represent all user specified constraints

            # add slots + values (where available) to the sys_act
            for k in keys:
                res = result[k] if result[k] and result[k]!='None' else 'not available'
                # prettify output format for opening hours
                if k == 'opening_hours' and res != 'not available':
                    opening_hours = json.loads(res)
                    res = '\n'
                    res += "\n".join("{}: {}".format(k, v) for k, v in opening_hours.items())
                if k == 'reviews' and res != 'not available':
                    res = res.replace("'", "\"")
                    reviews = json.loads(res)
                    res = '\n'
                    res += "\n".join("{}".format(rev) for rev in reviews)
                if k == 'parking_lot' and res != 'not available':
                    if res == '0':
                        res = 'no'
                    if res == '1':
                        res = 'a'
                if k == 'manner' and res != 'not available':
                    manner = json.loads(res)
                    res = ", ".join("{}".format(man) for man in manner)
                if k == 'description' and res != 'not available':
                    res = '\n' + res
                sys_act.add_value(k, res)
            # Name might not be a constraint in request queries, so add it
            if self.domain_key not in keys:
                name = self._get_name(beliefstate)
                sys_act.add_value(self.domain_key, name)
        else:
            sys_act.add_value(self.domain_key, 'none')

    def _convert_inform_by_alternatives(
            self, sys_act: SysAct, q_res: iter, beliefstate: BeliefState):
        """
            Helper Function, scrolls through the list of alternative entities which match the
            user's specified constraints and uses the next item in the list to fill in the raw
            inform act.

            When the end of the list is reached, currently continues to give last item in the list
            as a suggestion

            Args:
                sys_act (SysAct): the raw inform to be filled in
                beliefstate (BeliefState): current system belief state

        """
        if q_res and not self.current_suggestions:
            self.current_suggestions = []
            self.s_index = -1
            for result in q_res:
                self.current_suggestions.append(result)

        self.s_index += 1
        # here we should scroll through possible offers presenting one each turn the user asks
        # for alternatives
        if self.s_index <= len(self.current_suggestions) - 1:
            # the first time we inform, we should inform by name, so we use the right template
            if self.s_index == 0:
                sys_act.type = SysActionType.InformByName
            else:
                sys_act.type = SysActionType.InformByAlternatives
            result = self.current_suggestions[self.s_index]
            # Inform by alternatives according to our current templates is
            # just a normal inform apparently --LV
            sys_act.add_value(self.domain_key, result[self.domain_key])
        else:
            sys_act.type = SysActionType.InformByAlternatives
            # default to last suggestion in the list
            self.s_index = len(self.current_suggestions) - 1
            sys_act.add_value(self.domain.get_primary_key(), 'none')

        # in addition to the name, add the constraints the user has specified, so they know the
        # offer is relevant to them
        constraints, dontcare = self._get_constraints(beliefstate)
        for c in constraints:
            sys_act.add_value(c, constraints[c])

    def _convert_inform_by_constraints(self, q_results: iter,
                                       sys_act: SysAct, beliefstate: BeliefState):
        """
            Helper function for filling in slots and values of a raw inform act when the system is
            ready to make the user an offer

            Args:
                q_results (iter): the results from the databse query
                sys_act (SysAct): the raw infor act to be filled in
                beliefstate (BeliefState): the current system beliefs

        """
        # TODO: Do we want some way to allow users to scroll through
        # result set other than to type 'alternatives'? --LV
        if q_results:
            self.current_suggestions = []
            self.s_index = 0
            for result in q_results:
                self.current_suggestions.append(result)
            result = self.current_suggestions[0]
            sys_act.add_value(self.domain_key, result[self.domain_key])
        else:
            sys_act.add_value(self.domain_key, 'none')

        sys_act.type = SysActionType.InformByName
        constraints, dontcare = self._get_constraints(beliefstate)
        for c in constraints:
            # Using constraints here rather than results to deal with empty
            # results sets (eg. user requests something impossible) --LV
            sys_act.add_value(c, constraints[c])
