/* Modification */
/*
 * FLOWSIZE-tag.h
 *
 */

 #ifndef EXAMPLES_PLASTICINE_FLOWSIZE_TAG_H_
 #define EXAMPLES_PLASTICINE_FLOWSIZE_TAG_H_
 
 #include "ns3/packet.h"
 #include "ns3/tag.h"
 #include "ns3/uinteger.h"
 
 #include <iostream>
 
 namespace ns3
 {
 class FlowsizeTag : public Tag
 {
   public:
     /**
      * \brief Get the type ID.
      * \return the object TypeId
      */
     static TypeId GetTypeId(void);
     virtual TypeId GetInstanceTypeId(void) const;
     virtual uint32_t GetSerializedSize(void) const;
     virtual void Serialize(TagBuffer i) const;
     virtual void Deserialize(TagBuffer i);
     virtual void Print(std::ostream& os) const;
 
     void SetValue(uint32_t value);
     /**
      * Get the tag value
      * \return the tag value.
      */
     uint32_t GetValue(void) const;
 
   private:
     uint32_t m_value; //!< tag value
 };
 
 } // namespace ns3
 
 #endif 
/* EXAMPLES_PLASTICINE_FLOWSIZE_TAG_H_ */
/* Modification */
 